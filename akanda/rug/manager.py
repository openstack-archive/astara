import logging
import weakref

import netaddr
#from quantum.agent import rpc as agent_rpc
from quantumclient.v2_0 import client

from akanda.rug.openstack.common import cfg
from akanda.rug.openstack.common import manager
from akanda.rug.openstack.common import rpc
from akanda.rug.openstack.common import periodic_task

LOG = logging.getLogger(__name__)

OPTIONS = [
    cfg.StrOpt('admin_user'),
    cfg.StrOpt('admin_password'),
    cfg.StrOpt('admin_tenant_name'),
    cfg.StrOpt('auth_url'),
    cfg.StrOpt('auth_strategy', default='keystone'),
    cfg.StrOpt('auth_region'),
    cfg.IntOpt('task_interval', default=60)
]

cfg.CONF.register_opts(OPTIONS)

class RouterCache(object):
    def __init__(self):
        self.routers = {}
        self.router_by_tenant = weakref.WeakValueDictionary()
        self.router_by_tenant_network = weakref.WeakValueDictionary()
        self.router_by_tenant_subnet = weakref.WeakValueDictionary()
        self.router_by_port = weakref.WeakValueDictionary()

    def put(self, router):
        self.routers[router.id] = router
        self.router_by_tenant[router.tenant_id] = router

        for net in router.tenant_networks:
            self.router_by_tenant_network[net] = router

        for subnet in router.tenant_subnets:
            self.router_by_tenant_subnet = weakref.WeakValueDictionary()

        for port in router.tenant_ports:
            self.router_by_port[port.id] = router


class AkandaL3Manager(manager.Manager):
    def __init__(self):
        self.cache = RouterCache()

    def init_host(self):
        self.sync_state()
        #self.notifications = agent_rpc.NotificationDispatcher(self)

    def sync_state(self):
        pass

    @periodic_task.periodic_task
    def health_check(self):
        LOG.warn('health')

    @periodic_task.periodic_task(ticks_between_runs=5)
    def resync(self):
        LOG.warn('resync')
