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

from akanda.rug import commands
from akanda.rug.api import nova as nova_api
from akanda.rug.api import quantum as quantum_api
from akanda.rug.cli import message
from blessed import Terminal
from oslo.config import cfg


class BrowseRouters(message.MessageSending):

    log = logging.getLogger(__name__)

    def __init__(self, *a, **kw):
        self.term = Terminal()
        self.nova = nova_api.Nova(cfg.CONF)
        self.quantum = quantum_api.Quantum(cfg.CONF)
        self.position = 0
        super(BrowseRouters, self).__init__(*a, **kw)

    def take_action(self, parsed_args):
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
                    val = self.term.inkey(timeout=3)

    def fetch_routers(self):
        self.routers = self.quantum.get_routers()
        for router in self.routers:
            instance = self.nova.get_instance(router)
            if instance and instance.image:
                image = self.nova.client.images.get(instance.image['id'])
                status = self.term.red('OUT OF DATE')
                if image.id == cfg.CONF.router_image_uuid:
                    status = self.term.green('LATEST')
                name = status.ljust(11) + ' ' + image.name
                setattr(
                    router,
                    'image',
                    name
                )
            else:
                setattr(router, 'image', '<no vm>')

    def print_routers(self):
        visible_height = self.term.height - 2
        offset = 0
        if len(self.routers) > visible_height:
            offset = self.position
            offset = min(offset, len(self.routers) - visible_height - 1)
        routers = self.routers[offset:]
        with self.term.location():
            for i, r in enumerate(routers):
                if i > visible_height:
                    continue
                formatter = lambda x: x
                args = [
                    r.id,
                    r.name,
                    self.router_states[r.status](r.status.ljust(6)),
                    r.image
                ]
                if i + offset == self.position:
                    formatter = self.term.reverse
                print self.term.move(i, 0) + formatter(' '.join(args)).ljust(
                    self.term.width
                )

    def make_message(self, router):
        return {
            'command': commands.ROUTER_REBUILD,
            'router_id': router.id,
            'tenant_id': router.tenant_id
        }

    def rebuild_router(self):
        router = self.routers[self.position]
        router.status = 'DOWN'
        self.send_message(self.make_message(router))

    def move_up(self):
        self.position = max(0, self.position-1)

    def move_down(self):
        self.position = min(len(self.routers)-1, self.position+1)

    @property
    def router_states(self):
        return {
            'ACTIVE': self.term.green,
            'BUILD': self.term.yellow,
            'DOWN': self.term.red,
            'ERROR': self.term.red
        }
