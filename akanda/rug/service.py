import socket
import sys

import eventlet
from oslo.config import cfg

from akanda.rug import manager
from akanda.rug.openstack.common import log
from akanda.rug.openstack.common import rpc
from akanda.rug.openstack.common.rpc import service as rpc_service
from akanda.rug.openstack.common import service

L3_AGENT_TOPIC = 'l3_agent'
cfg.CONF.register_opts([
    cfg.IntOpt('periodic_interval',
               default=60,
               help='seconds between periodic task runs (ie health check)'),
    cfg.StrOpt('host',
               default=socket.getfqdn(),
               help=_("The hostname Quantum is running on")),
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
    cfg.CONF(sys.argv[1:], project='akanda')
    log.setup('akanda')

    mgr = manager.AkandaL3Manager()
    svc = PeriodicService(
        host=cfg.CONF.host, topic=L3_AGENT_TOPIC, manager=mgr
    )
    service.launch(svc).wait()


if __name__ == '__main__':
    main()
