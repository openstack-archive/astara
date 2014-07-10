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
import time
import sqlite3
import tempfile

from akanda.rug import commands
from akanda.rug.api import nova as nova_api
from akanda.rug.api import quantum as quantum_api
from akanda.rug.cli import message
from blessed import Terminal
from oslo.config import cfg


class ConfigSub(object):

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

    def __init__(self, *args):
        self.id, self.name, self.status, self.latest, self.image_name = args
        self.tenant_id = self.name.replace('ak-', '')
        self.image_name = self.image_name or '<no vm>'


class RouterFetcher(object):

    def __init__(self, conf, db):
        self.conn = sqlite3.connect(db)
        self.nova = nova_api.Nova(conf)
        self.quantum = quantum_api.Quantum(conf)

    def fetch(self):
        routers = self.quantum.get_routers()
        c = self.conn.cursor()
        for router in routers:
            instance = None
            image = None
            try:
                instance = self.nova.get_instance(router)
            except:
                pass
            if instance and instance.image:
                image = self.nova.client.images.get(instance.image['id'])
            sql = ''.join([
                "INSERT OR REPLACE INTO routers ",
                "('id', 'name', 'status', 'latest', 'image_name') VALUES (",
                ', '.join("?" * 5),
                ");"
            ])
            c.execute(sql, (
                router.id,
                router.name,
                router.status,
                image and image.id == cfg.CONF.router_image_uuid,
                image.name if image else ''
            ))
            self.conn.commit()


def populate_routers(db, *args):
    conf = ConfigSub(*args)
    client = RouterFetcher(conf, db)
    while True:
        client.fetch()
        time.sleep(.1)


class BrowseRouters(message.MessageSending):

    log = logging.getLogger(__name__)
    SCHEMA = '''CREATE TABLE routers (
        id TEXT PRIMARY KEY,
        name TEXT,
        status TEXT,
        latest INTEGER,
        image_name TEXT
    );'''

    def __init__(self, *a, **kw):
        self.term = Terminal()
        self.position = 0
        self.init_database()
        p = multiprocessing.Process(
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
        p.start()
        super(BrowseRouters, self).__init__(*a, **kw)

    def init_database(self):
        self.fh = tempfile.NamedTemporaryFile()
        self.conn = sqlite3.connect(self.fh.name)
        c = self.conn.cursor()
        c.execute(self.SCHEMA)
        self.conn.commit()

    def take_action(self, parsed_args):
        with self.term.fullscreen():
            with self.term.cbreak():
                val = None
                while val != u'q':
                    if val and val.is_sequence:
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

    def clean_up(self, cmd, result, err):
        self.fh.close()
        return super(BrowseRouters).clean_up(cmd, result, err)

    @property
    def routers(self):
        c = self.conn.cursor()
        c.execute('SELECT * FROM routers ORDER BY id ASC;')
        return [RouterRow(*row) for row in c.fetchall()]

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
                age = self.term.red('OUT-OF-DATE')
                if r.latest:
                    age = self.term.green('LATEST'.ljust(11))
                args = [
                    r.id,
                    r.name,
                    self.router_states[r.status](r.status.ljust(7)),
                    age,
                    r.image_name
                ]
                if i + offset == self.position:
                    args = map(self.term.reverse, args)
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
        c = self.conn.cursor()
        c.execute('UPDATE routers SET status=? WHERE id=?', ('REBUILD', r.id))
        self.conn.commit()
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
