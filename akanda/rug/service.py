import sys

from akanda.rug import manager
from akanda.rug.openstack.common import cfg
from akanda.rug.openstack.common import log
from akanda.rug.openstack.common import service

cfg.CONF.register_opts([
    cfg.IntOpt('periodic_interval',
               default=60,
               help='seconds between running periodic tasks (ie health check)')
])


def main():
    cfg.CONF(sys.argv[1:])
    log.setup('akanda')

    mgr = manager.AkandaL3Manager()
    svc = service.Service('akanda', mgr, cfg.CONF.periodic_interval, None)
    svc.start()
    svc.wait()


if __name__ == '__main__':
    main()
