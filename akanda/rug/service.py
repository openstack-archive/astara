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


import socket
import sys

import eventlet
from oslo.config import cfg
from oslo_log import log

from akanda.rug import manager
from akanda.rug.openstack.common.gettextutils import _
from akanda.rug.openstack.common.rpc import service as rpc_service
from akanda.rug.openstack.common import service


L3_AGENT_TOPIC = 'l3_agent'
cfg.CONF.register_opts([
    cfg.IntOpt('periodic_interval',
               default=60,
               help='seconds between periodic task runs (ie health check)'),
    cfg.StrOpt('host',
               default=socket.getfqdn(),
               help=_("The hostname Neutron is running on")),
])


class PeriodicService(rpc_service.Service):
    def start(self):
        super(PeriodicService, self).start()
        self.tg.add_timer(
            cfg.CONF.periodic_interval,
            self.manager.run_periodic_tasks,
            None,
            None
        )


def main():
    eventlet.monkey_patch()
    cfg.CONF(sys.argv[1:], project='akanda-rug')
    log.setup('akanda')

    mgr = manager.AkandaL3Manager()
    svc = PeriodicService(
        host=cfg.CONF.host, topic=L3_AGENT_TOPIC, manager=mgr
    )
    service.launch(svc).wait()


if __name__ == '__main__':
    main()
