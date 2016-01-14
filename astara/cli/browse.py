# Copyright 2014 DreamHost, LLC
#
# Author: DreamHost, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


"""Interactive CLI for rebuilding routers
"""
import logging
import os
import Queue
import sqlite3
import tempfile
import threading
import six
from contextlib import closing
from datetime import datetime

try:
    from blessed import Terminal
except ImportError:
    # blessed is not part of openstack global-requirements.
    raise Exception("The 'blessed' python module is required to browse"
                    " Astara routers. Please install and try again.")

from oslo_config import cfg

from astara import commands
from astara.api import nova as nova_api
from astara.api import neutron as neutron_api
from astara.cli import message

logging.getLogger("urllib3").setLevel(logging.ERROR)

cfg.CONF.import_opt('host', 'astara.main')


class FakeConfig(object):

    def __init__(self, admin_user, admin_password, tenant_name, auth_url,
                 auth_strategy, auth_region, instance_provider):
        self.admin_user = admin_user
        self.admin_password = admin_password
        self.tenant_name = tenant_name
        self.admin_tenant_name = tenant_name
        self.auth_url = auth_url
        self.auth_strategy = auth_strategy
        self.auth_region = auth_region
        self.instance_provider = instance_provider


class RouterRow(object):

    id = None
    name = None
    status = None
    latest = None
    image_name = None
    booted_at = None
    last_fetch = None
    nova_status = None

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

        self.image_name = self.image_name or ''
        self.booted_at = self.booted_at or ''
        self.nova_status = self.nova_status or ''
        if self.name:
            self.tenant_id = self.name.replace('ak-', '')

    @classmethod
    def from_cursor(cls, cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return cls(**d)


class RouterFetcher(object):

    def __init__(self, conf, db, workers):
        self.db = db
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = RouterRow.from_cursor
        self.nova = nova_api.Nova(conf)
        self.neutron = neutron_api.Neutron(conf)
        self.nova_queue = Queue.Queue()
        self.save_queue = Queue.Queue()

        # Create X threads to perform Nova calls and put results into a queue
        threads = [
            threading.Thread(
                name='fetcher-t%02d' % i,
                target=self.fetch_router_metadata,
            )
            for i in six.moves.range(workers)
        ]
        for t in threads:
            t.setDaemon(True)
            t.start()

    def fetch(self):
        routers = self.neutron.get_routers(detailed=False)
        routers.sort(key=lambda x: x.id)
        for router in routers:
            sql = ''.join([
                "INSERT OR IGNORE INTO routers ",
                "('id', 'name', 'latest') VALUES (",
                ', '.join("?" * 3),
                ");"
            ])

            with closing(self.conn.cursor()) as cursor:
                cursor.execute(
                    'SELECT * FROM routers WHERE id=?;',
                    (router.id,)
                )
                current_router = cursor.fetchone()

                if router.status not in ('BUILD', 'ACTIVE') and \
                        current_router and current_router.status == 'BOOT':
                    continue

                cursor.execute(sql, (router.id, router.name, None))
                cursor.execute(
                    'UPDATE routers SET status=? WHERE id=?',
                    (router.status, router.id)
                )
                self.conn.commit()
            self.nova_queue.put(router.id)

        # SQLite databases have global database-wide lock for writes, so
        # we can't split the writes across threads.  That's okay, though, the
        # slowness isn't the DB writes, it's the Nova API calls
        while True:
            try:
                router, latest, name, booted_at, nova_status = \
                    self.save_queue.get(False)
                with closing(self.conn.cursor()) as cursor:
                    cursor.execute(
                        'UPDATE routers SET latest=?, image_name=?, '
                        'last_fetch=?, booted_at=? WHERE id=?',
                        (latest, name, datetime.utcnow(), booted_at, router)
                    )
                    if nova_status == 'BUILD':
                        cursor.execute(
                            'UPDATE routers SET status=? WHERE id=?',
                            ('BOOT', router)
                        )
                    self.conn.commit()
                self.save_queue.task_done()
            except Queue.Empty:
                # the queue *might* be empty, and that's okay
                break

    def fetch_router_metadata(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = RouterRow.from_cursor
        while True:
            router = RouterRow(id=self.nova_queue.get())
            image = None
            try:
                instance = self.nova.get_instance(router)
                image = self.nova.client.images.get(instance.image['id'])
            except:
                pass
            if image:
                self.save_queue.put((
                    router.id,
                    image.id == cfg.CONF.router_image_uuid,
                    image.name,
                    instance.created,
                    instance.status
                ))
            else:
                self.save_queue.put((
                    router.id,
                    None,
                    None,
                    None,
                    None
                ))
            self.nova_queue.task_done()


def populate_routers(db, conf, workers):
    conf = FakeConfig(*conf)
    client = RouterFetcher(conf, db, workers)
    while True:
        try:
            client.fetch()
        except (KeyboardInterrupt, SystemExit):
            print "Killing background worker..."
            break


class BrowseRouters(message.MessageSending):
    """browse the state of every Astara appliance"""

    log = logging.getLogger(__name__)
    interactive = True

    SCHEMA = '''CREATE TABLE routers (
        id TEXT PRIMARY KEY,
        name TEXT,
        status TEXT,
        latest INTEGER,
        image_name TEXT,
        last_fetch TIMESTAMP,
        booted_at TIMESTAMP
    );'''

    def __init__(self, *a, **kw):
        self.term = Terminal()
        self.position = 0
        self.routers = []
        super(BrowseRouters, self).__init__(*a, **kw)

    def init_database(self):
        self.fh = tempfile.NamedTemporaryFile(delete=False)
        self.conn = sqlite3.connect(self.fh.name)
        self.conn.row_factory = RouterRow.from_cursor
        with closing(self.conn.cursor()) as cursor:
            cursor.execute(self.SCHEMA)

    def get_parser(self, prog_name):
        parser = super(BrowseRouters, self).get_parser(prog_name)
        parser.add_argument('--dump', dest='interactive', action='store_false')
        parser.add_argument('--threads', type=int, default=16)
        parser.set_defaults(interactive=True)
        return parser

    def take_action(self, parsed_args):
        self.interactive = parsed_args.interactive
        self.init_database()
        credentials = [
            cfg.CONF.admin_user,
            cfg.CONF.admin_password,
            cfg.CONF.admin_tenant_name,
            cfg.CONF.auth_url,
            cfg.CONF.auth_strategy,
            cfg.CONF.auth_region,
            cfg.CONF.instance_provider
        ]
        populate = threading.Thread(
            name='router-populater',
            target=populate_routers,
            args=(self.fh.name, credentials, parsed_args.threads)
        )
        populate.setDaemon(True)
        populate.start()
        self.handle_loop()

    def handle_loop(self):
        try:
            with self.term.fullscreen():
                with self.term.cbreak():
                    val = None
                    while val != u'q':
                        if not val:
                            self.fetch_routers()
                        elif val.is_sequence:
                            if val.code == self.term.KEY_DOWN:
                                self.move_down()
                            if val.code == self.term.KEY_UP:
                                self.move_up()
                        elif val == u'j':
                            self.move_down()
                        elif val == u'k':
                            self.move_up()
                        elif val == u'r':
                            self.rebuild_router()
                        if self.interactive:
                            self.print_routers()
                            val = self.term.inkey(timeout=3)
                        elif len(self.routers) and all(map(
                            lambda x: x.last_fetch, self.routers
                        )):
                            self.print_routers()
                            val = u'q'
                    self._exit()
        except KeyboardInterrupt:
            self._exit()
            raise

    def fetch_routers(self):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM routers ORDER BY id ASC;')
            self.routers = cursor.fetchall()

    @property
    def window(self):
        offset = 0
        routers = self.routers
        visible_height = self.term.height - 2
        if len(routers) > visible_height:
            offset = self.position
            offset = min(offset, len(routers) - visible_height - 1)
        return offset, routers[offset:(offset+visible_height+1)]

    def print_routers(self):
        offset, routers = self.window
        with self.term.location():
            for i, r in enumerate(routers):
                if r.latest is None:
                    age = '<loading>'.ljust(11)
                elif r.latest:
                    age = self.term.green('LATEST'.ljust(11))
                elif not r.latest:
                    age = self.term.red('OUT-OF-DATE')
                args = [
                    r.id,
                    r.name,
                    self.router_states[r.status](r.status.ljust(7)),
                    age,
                    r.image_name,
                    'at',
                    r.booted_at
                ]
                if i + offset == self.position:
                    args = map(self.term.reverse, args[:-3]) + args[-3:]
                print self.term.move(i, 0) + ' '.join(args)

    def make_message(self, router):
        return {
            'command': commands.ROUTER_REBUILD,
            'router_id': router.id,
            'tenant_id': router.tenant_id
        }

    def rebuild_router(self):
        offset, routers = self.window
        r = routers[self.position-offset]
        r.status = 'REBUILD'
        self.send_message(self.make_message(r))

    def move_up(self):
        self.position = max(0, self.position-1)

    def move_down(self):
        self.position = min(len(self.routers)-1, self.position+1)

    @property
    def router_states(self):
        return {
            'ACTIVE': self.term.green,
            'BUILD': self.term.yellow,
            'BOOT': self.term.yellow,
            'REBUILD': self.term.yellow,
            'DOWN': self.term.red,
            'ERROR': self.term.red
        }

    def _exit(self):
        if self.interactive:
            print 'Deleting %s...' % self.fh.name
        self.fh.close()
        os.remove(self.fh.name)
        if self.interactive:
            print 'Exiting...'
