import logging
import weakref

import eventlet
import netaddr
from quantumclient.v2_0 import client

from akanda.rug.lib import nova
from akanda.rug.lib import quantum
from akanda.rug.lib import rest
from akanda.rug.openstack.common import cfg
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
    cfg.StrOpt('management_network_id'),
    cfg.StrOpt('management_subnet_id'),
    cfg.StrOpt('router_image_uuid'),
    cfg.StrOpt('management_prefix', default='fdca:3ba5:a17a:acda::/64'),
    cfg.IntOpt('akanda_mgt_service_port', default=5000),
    cfg.IntOpt('router_instance_flavor', default=1),
    cfg.StrOpt('interface_driver'),
    cfg.StrOpt('ovs_integration_bridge', default='br-int'),
    cfg.StrOpt('root_helper', default='sudo'),
    cfg.IntOpt('network_device_mtu'),
    cfg.StrOpt('quantum_notification_topic', default='notifications.info')
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

        for port in router.internal_ports:
            self.router_by_port[port.id] = router
            self.router_by_tenant_network[port.network_id] = router

            for fixed in port.fixed_ips:
                self.router_by_tenant_subnet[fixed.subnet_id] = router

    def remove(self, router_id):
        try:
            del self.routers[router_id]
        except KeyError:
            pass

    def get(self, key, default=None):
        try:
            return self.routers[key]
        except KeyError:
            return default

    def get_by_tenant_id(self, tenant_id):
        return self.router_by_tenant.get(tenant_id)

    def keys(self):
        return self.routers.keys()


class AkandaL3Manager(periodic_task.PeriodicTasks):
    def __init__(self):
        self.cache = RouterCache()
        self.quantum = quantum.Quantum(cfg.CONF)
        self.nova = nova.Nova(cfg.CONF)
        self.task_queue = eventlet.queue.Queue()
        self.delay_queue = eventlet.queue.Queue()

        self.quantum.ensure_local_service_port()

    def init_host(self):
        self.sync_state()
        eventlet.spawn(self._serialized_task_runner)
        self.create_notification_listener()

    def sync_state(self):
        """Load state from database and update routers that have changed."""
        # pull all known routers
        routers = self.quantum.get_routers()

        # now compare to see if they are the same
        for rtr in routers.values():
            if not rtr.internal_ports:
                # remove routers without any internal ports
                self.task_queue.put((self._delete_router, rtr.id))
            elif self.cache.get(rtr.id) != rtr:
                # activate any missing routers or
                # updating routers with new configs
                self.task_queue.put((self._update_router, rtr.id))

    @periodic_task.periodic_task
    def health_check(self):
        LOG.warn('health check')

    @periodic_task.periodic_task(ticks_between_runs=5)
    def resync(self):
        LOG.debug('resync router state')
        self.sync_state()

    @periodic_task.periodic_task(ticks_between_runs=10)
    def refresh_configs(self):
        LOG.debug('resync configuration state')

    @periodic_task.periodic_task
    def delayed_task_requeue(self):
        LOG.warn('requeuing delayed tasked')
        while 1:
            try:
                item = self.delay_queue.get_nowait()
                self.task_queue.put(item)
            except eventlet.queue.Empty:
                break

    def create_notification_listener(self):
        self.connection = rpc.create_connection(new=True)
        self.connection.declare_topic_consumer(
            topic=cfg.CONF.quantum_notification_topic,
            callback=self._notification_dispatcher)
        self.connection.consume_in_thread()

    def _notification_dispatcher(self, msg):
        handler_name = '_' + msg['event_type'].replace('.', '_')

        try:
            LOG.debug('Dispatching: %s' % handler_name)
            if hasattr(self, handler_name):
                h = getattr(self, handler_name)
                h(msg['_context_tenant_id'], msg['payload'])
        except Exception, e:
            LOG.exception('Error processing notification.')

    def _port_update(self, tenant_id, payload):
        rtr = self.cache.get_by_tenant_id(tenant_id)

        if rtr:
            self.task_queue.put((self._update_router, rtr.id))

    _port_create_end = _port_update
    _port_delete_end = _port_update

    def _router_create_end(self, tenant_id, payload):
        self.task_queue.put((self._update_router, payload['router']['id']))

    def _router_delete_end(self, tenant_id, payload):
        self.task_queue.put((self._delete_router, payload['router_id']))

    def _subnet_change(self, tenant_id, payload):
        rtr = self.cache.get_by_tenant_id(tenant_id)
        if rtr:
            self.task_queue.put((self._update_router_subnets, rtr.id))

    _subnet_create_end = _subnet_change
    _subnet_delete_end = _subnet_change
    _subnet_update_end = _subnet_change

    def _serialized_task_runner(self):
        while True:
            LOG.warn('Waiting on item')
            action, router_id = self.task_queue.get()

            try:
                action(router_id)
            except:
                LOG.exception('unable to %s' % action.__name__)
                self.delay_queue.put((action, router_id))

    def _update_router(self, router_id):
        LOG.warn('Updating router: %s' % router_id)
        rtr = self.quantum.get_router_detail(router_id)

        if rtr.management_port is None:
            mgt_port = self.quantum.create_router_management_port(rtr.id)
            rtr.management_port = mgt_port
            self._boot_router_instance(rtr)
        elif 1 or self._router_is_alive(rtr):
            # if the internal ports of have changed we'll reboot for now
            # FIXME: change this to carp failover
            prev = self.cache.get(rtr.id)
            if prev and prev.internal_ports != rtr.internal_ports:
                self._reboot_router_instance(rtr)
            else:
                self._update_router_configuration(rtr)
        else:
            # FIXME: change this to carp failover"
            self._reboot_router_instance(rtr)
        self.cache.put(rtr)

    def _delete_router(self, router_id):
        LOG.warn('Deleting router: %s' % router_id)
        rtr = self.quantum.get_router_detail(router_id)

        if rtr.management_port is None:
            return
        self._kill_router_instance()
        self.cache.remove(rtr)

    def _update_router_subnets(self, router_id):
        LOG.warn('update router subnets')
        #XXX Do we automatically add subnets to routers?

    def _router_is_alive(self, router):
        return rest.is_alive(_get_management_address(router),
                             cfg.CONF.akanda_mgt_service_port)

    def _boot_router_instance(self, router):
        self.nova.create_router_instance(router)
        # TODO: add thread that waits until this router is functional

    def _reboot_router_instance(self, router):
        self.nova.reboot_router_instance(router)
        # TODO: add thread that waits until this router is functional

    def _update_router_configuration(self, router):
        LOG.warn('push router config')


def _get_management_address(router):
    prefix, prefix_len = cfg.CONF.management_prefix.split('/', 1)
    eui = netaddr.EUI(router.management_port.mac_address)
    return str(eui.ipv6_link_local()).replace('fe80::', prefix[:-1])
