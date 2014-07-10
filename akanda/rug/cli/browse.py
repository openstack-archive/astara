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
import multiprocessing
import os
import Queue
import sqlite3
import tempfile
import threading
from contextlib import closing
from datetime import datetime

from akanda.rug import commands
from akanda.rug.api import nova as nova_api
from akanda.rug.api import quantum as quantum_api
from akanda.rug.cli import message
from blessed import Terminal
from oslo.config import cfg


class FakeConfig(object):

    def __init__(self, admin_user, admin_password, tenant_name, auth_url,
                 auth_strategy, auth_region):
        self.admin_user = admin_user
        self.admin_password = admin_password
        self.tenant_name = tenant_name
        self.admin_tenant_name = tenant_name
        self.auth_url = auth_url
        self.auth_strategy = auth_strategy
        self.auth_region = auth_region


class RouterRow(object):

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

        self.image_name = self.image_name or ''
        self.tenant_id = self.name.replace('ak-', '')

    @classmethod
    def from_cursor(cls, cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return cls(**d)


class RouterFetcher(object):

    def __init__(self, conf, db, num_threads=8):
        self.db = db
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = RouterRow.from_cursor
        self.nova = nova_api.Nova(conf)
        self.quantum = quantum_api.Quantum(conf)
        self.queue = Queue.Queue()

        # Create X threads to perform Nova calls and put results into a queue
        threads = [
            threading.Thread(
                name='fetcher-t%02d' % i,
                target=self.fetch_router_metadata,
            )
            for i in xrange(num_threads)
        ]
        for t in threads:
            t.setDaemon(True)
            t.start()

    def fetch(self):
        routers = self.quantum.get_routers()
        for router in routers:
            sql = ''.join([
                "INSERT OR IGNORE INTO routers ",
                "('id', 'name', 'latest') VALUES (",
                ', '.join("?" * 3),
                ");"
            ])
            with closing(self.conn.cursor()) as cursor:
                cursor.execute(sql, (router.id, router.name, None))
                cursor.execute(
                    'UPDATE routers SET status=? WHERE id=?',
                    (router.status, router.id)
                )
                self.conn.commit()

        # SQLite databases have global database-wide lock for writes, so
        # we can't split the writes across threads.  That's okay, though, the
        # slowness isn't the DB writes, it's the Nova API calls
        while True:
            try:
                router, latest, name = self.queue.get(False)
                with closing(self.conn.cursor()) as cursor:
                    cursor.execute(
                        'UPDATE routers SET latest=?, image_name=?, '
                        'last_fetch=? WHERE id=?',
                        (latest, name, datetime.utcnow(), router)
                    )
                    self.conn.commit()
                self.queue.task_done()
            except Queue.Empty:
                # the queue *might* be empty, and that's okay
                break

    def fetch_router_metadata(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = RouterRow.from_cursor
        while True:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    'SELECT * FROM routers WHERE last_fetch = NULL '
                    'ORDER BY id ASC LIMIT 1;'
                )
                router = cursor.fetchone()
                if router is None:
                    cursor.execute(
                        'SELECT * FROM routers '
                        'ORDER BY last_fetch ASC, RANDOM() LIMIT 1;'
                    )
                    router = cursor.fetchone()

            if router:
                try:
                    instance = self.nova.get_instance(router)
                except:
                    pass
                if instance and instance.image:
                    image = self.nova.client.images.get(
                        instance.image['id']
                    )
                    if image:
                        self.queue.put((
                            router.id,
                            image.id == cfg.CONF.router_image_uuid,
                            image.name
                        ))


def populate_routers(db, *args):
    conf = FakeConfig(*args)
    client = RouterFetcher(conf, db)
    while True:
        try:
            client.fetch()
        except (KeyboardInterrupt, SystemExit):
            print "Killing background worker..."
            break


class BrowseRouters(message.MessageSending):

    log = logging.getLogger(__name__)
    SCHEMA = '''CREATE TABLE routers (
        id TEXT PRIMARY KEY,
        name TEXT,
        status TEXT,
        latest INTEGER,
        image_name TEXT,
        last_fetch TIMESTAMP
    );'''

    def __init__(self, *a, **kw):
        self.term = Terminal()
        self.position = 0
        self.routers = []
        self.init_database()
        self.process = multiprocessing.Process(
            target=populate_routers,
            args=(
                self.fh.name,
                cfg.CONF.admin_user,
                cfg.CONF.admin_password,
                cfg.CONF.admin_tenant_name,
                cfg.CONF.auth_url,
                cfg.CONF.auth_strategy,
                cfg.CONF.auth_region
            )
        )
        self.process.start()
        super(BrowseRouters, self).__init__(*a, **kw)

    def init_database(self):
        self.fh = tempfile.NamedTemporaryFile(delete=False)
        self.conn = sqlite3.connect(self.fh.name)
        self.conn.row_factory = RouterRow.from_cursor
        with closing(self.conn.cursor()) as cursor:
            cursor.execute(self.SCHEMA)

    def take_action(self, parsed_args):
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
                        self.print_routers()
                        val = self.term.inkey(timeout=1)
                    self.process.terminate()
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
                    r.image_name.ljust(self.term.width)
                ]
                if i + offset == self.position:
                    args = map(self.term.reverse, args[:-2]) + args[-2:]
                print self.term.move(i, 0) + ' '.join(args).ljust(
                    self.term.width
                )

    def make_message(self, router):
        return {
            'command': commands.ROUTER_REBUILD,
            'router_id': router.id,
            'tenant_id': router.tenant_id
        }

    def rebuild_router(self):
        r = self.routers[self.position]
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
            'REBUILD': self.term.yellow,
            'DOWN': self.term.red,
            'ERROR': self.term.red
        }

    def _exit(self):
        print 'Deleting %s...' % self.fh.name
        self.fh.close()
        os.remove(self.fh.name)
        print 'Exiting...'
