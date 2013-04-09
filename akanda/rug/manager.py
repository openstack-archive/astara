import logging
import weakref

import eventlet
import netaddr
from oslo.config import cfg

from akanda.rug.api import configuration
from akanda.rug.api import nova
from akanda.rug.api import quantum
from akanda.rug.api import akanda_client as router_api
from akanda.rug.common import cache
from akanda.rug.common import notification
from akanda.rug.common import task
from akanda.rug import metadata
from akanda.rug.openstack.common import context
from akanda.rug.openstack.common import periodic_task
from akanda.rug.openstack.common import rpc
from akanda.rug.openstack.common import timeutils

LOG = logging.getLogger(__name__)

OPTIONS = [
    cfg.StrOpt('admin_user'),
    cfg.StrOpt('admin_password', secret=True),
    cfg.StrOpt('admin_tenant_name'),
    cfg.StrOpt('auth_url'),
    cfg.StrOpt('auth_strategy', default='keystone'),
    cfg.StrOpt('auth_region'),

    cfg.StrOpt('management_network_id'),
    cfg.StrOpt('external_network_id'),
    cfg.StrOpt('management_subnet_id'),
    cfg.StrOpt('router_image_uuid'),

    cfg.StrOpt('management_prefix', default='fdca:3ba5:a17a:acda::/64'),
    cfg.IntOpt('akanda_mgt_service_port', default=5000),
    cfg.IntOpt('router_instance_flavor', default=1),

    # needed for plugging locally into management network
    cfg.StrOpt('interface_driver'),
    cfg.StrOpt('ovs_integration_bridge', default='br-int'),
    cfg.BoolOpt('ovs_use_veth', default=False),
    cfg.IntOpt('network_device_mtu'),

    # listen for Quantum notification events
    cfg.StrOpt('notification_topic',
               default='notifications.info',
               help='Quantum notification topic name')
]

AGENT_OPTIONS = [
    cfg.StrOpt('root_helper', default='sudo'),
]

cfg.CONF.register_opts(OPTIONS)
cfg.CONF.register_opts(AGENT_OPTIONS, 'AGENT')


class AkandaL3Manager(notification.NotificationMixin,
                      periodic_task.PeriodicTasks):
    def __init__(self):
        self.cache = cache.RouterCache()
        self.quantum = quantum.Quantum(cfg.CONF)
        self.nova = nova.Nova(cfg.CONF)
        self.task_mgr = task.TaskManager()
        self.quantum.ensure_local_service_port()

    def initialize_service_hook(self, started_by):
        self.sync_state()
        self.task_mgr.start()
        self.create_notification_listener(
            cfg.CONF.notification_topic,
            cfg.CONF.control_exchange)
        self.metadata = metadata.create_metadata_signing_proxy(
            quantum.get_local_service_ip(cfg.CONF).split('/')[0]
        )

    @periodic_task.periodic_task
    def begin_health_check(self, context):
        LOG.info('start health check queueing')
        for rtr in self.cache.routers():
            self.task_mgr.put(self.check_health, rtr)

    @periodic_task.periodic_task(ticks_between_runs=1)
    def report_bandwidth_usage(self, context):
        LOG.info('start bandwidth usage reporting')
        for rtr in self.cache.routers():
            self.task_mgr.put(self.report_bandwidth, rtr)

    @periodic_task.periodic_task(ticks_between_runs=10)
    def janitor(self, context):
        """Periodically do a full state resync."""
        LOG.debug('resync router state')
        self.sync_state()

    @periodic_task.periodic_task(ticks_between_runs=15)
    def refresh_configs(self, context):
        LOG.debug('resync configuration state')
        for rtr_id in self.cache.keys():
            self.task_mgr.put(self.update_router, rtr_id)

    # notification handlers
    def default_notifcation_handler(self, event_type, tenant_id, payload):
        parts = event_type.split('.')
        if parts and parts[-1] == 'end':
            rtr = self.cache.get_by_tenant_id(tenant_id)
            if rtr:
                self.task_mgr.put(self.update_router, rtr.id)

    @notification.handles('subnet.create.end',
                          'subnet.change.end',
                          'subnet.delete.end',
                          'port.create.end',
                          'port.change.end',
                          'port.delete.end')
    def handle_router_subnet_change(self, tenant_id, payload):
        rtr = self.cache.get_by_tenant_id(tenant_id)
        if not rtr:
            rtr = self.quantum.get_router_for_tenant(tenant_id)

        if rtr:
            self.task_mgr.put(self.update_router, rtr.id)

    @notification.handles('router.create.end')
    def handle_router_create_notification(self, tenant_id, payload):
        self.task_mgr.put(self.update_router, payload['router']['id'])

    @notification.handles('router.delete.end')
    def handle_router_delete_notification(self, tenant_id, payload):
        self.task_mgr.put(self.destroy_router, payload['router_id'])

    def routers_updated(self, context, routers):
        """Method for Quantum L3 Agent API"""
        for r in routers:
            self.task_mgr.put(self.update_router, r['id'])

    def router_deleted(self, context, routers):
        """ Method for Quamtum L3 Agent API"""
        for r in routers:
            self.task_mgr.put(self.destroy_router, r['id'])

    def sync_state(self):
        """Load state from database and update routers that have changed."""
        # pull all known routers
        known_routers = set(self.cache.keys())
        active_routers = set()

        for rtr in self.quantum.get_routers():
            active_routers.add(rtr.id)

            if self.cache.get(rtr.id) != rtr:
                self.task_mgr.put(self.update_router, rtr.id)

        for rtr_id in (known_routers - active_routers):
            self.task_mgr.put(self.destroy_router, rtr_id)

    def update_router(self, router_id):
        LOG.debug('Updating router: %s' % router_id)

        rtr = self.quantum.get_router_detail(router_id)
        self.ensure_provider_ports(rtr)

        if self.router_is_alive(rtr) and self.verify_router_interfaces(rtr):
            self.update_config(rtr)
        else:
            # FIXME: change this to carp failover"
            self.reboot_router(rtr)
        self.cache.put(rtr)

    def destroy_router(self, router_id):
        LOG.debug('Destroying router: %s' % router_id)
        rtr = self.cache.get(router_id)
        if rtr:
            self.nova.destroy_router_instance(rtr)
            self.cache.remove(rtr)

    def reboot_router(self, router):
        self.nova.reboot_router_instance(router)
        # TODO: add thread that waits until this router is functional
        self.task_mgr.put(self._post_reboot, router, 30)

    def _post_reboot(self, router):
        if self.router_is_alive(router):
            self.task_mgr.put(self.update_router, router.id)
        else:
            raise Warning('Router %s has not finished booting. IP: %s' %
                          (router.id, _get_management_address(router)))

    def update_config(self, router):
        LOG.debug('Updating router %s config' % router.id)
        interfaces = router_api.get_interfaces(
            _get_management_address(router),
            cfg.CONF.akanda_mgt_service_port)

        config = configuration.build_config(self.quantum, router, interfaces)

        router_api.update_config(_get_management_address(router),
                                 cfg.CONF.akanda_mgt_service_port,
                                 config)
        LOG.debug('Router %s config updated.' % router.id)

    def router_is_alive(self, router):
        return router_api.is_alive(_get_management_address(router),
                                   cfg.CONF.akanda_mgt_service_port)

    def verify_router_interfaces(self, router):
        try:
            interfaces = router_api.get_interfaces(
                _get_management_address(router),
                cfg.CONF.akanda_mgt_service_port)

            router_macs = set([iface['lladdr'] for iface in interfaces])

            expected_macs = set([p.mac_address for p in router.internal_ports])
            expected_macs.add(router.management_port.mac_address)
            expected_macs.add(router.external_port.mac_address)
            return router_macs == expected_macs

        except:
            LOG.exception('Unable verify interfaces.')

    def report_bandwidth(self, router):
        try:
            bandwidth = router_api.read_labels(
                _get_management_address(router),
                cfg.CONF.akanda_mgt_service_port)

            if bandwidth:
                message = {
                    'tenant_id': router.tenant_id,
                    'timestamp': timeutils.isotime(),
                    'event_type': 'akanda.bandwidth.used',
                    'payload': dict((b.pop('name'), b) for b in bandwidth)
                }

                rpc.notify(context.get_admin_context(),
                           cfg.CONF.notification_topic,
                           message)
        except:
            LOG.exception('Error during bandwidth report.')

    def check_health(self, router):
            if not self.router_is_alive(router):
                status = self.nova.get_router_instance_status(router)
                if status not in ('ACTIVE', 'REBOOT', 'BUILD'):
                    self.task_mgr.put(self.reboot_router, router)

    def ensure_provider_ports(self, router):
        if router.management_port is None:
            mgt_port = self.quantum.create_router_management_port(router.id)
            router.management_port = mgt_port

        if router.external_port is None:
            ext_port = self.quantum.create_router_external_port(router)
            router.external_port = ext_port

        return router


def _get_management_address(router):
    network = netaddr.IPNetwork(cfg.CONF.management_prefix)

    tokens = ['%02x' % int(t, 16)
              for t in router.management_port.mac_address.split(':')]

    eui64 = int(
        ''.join(tokens[0:3] + ['ff', 'fe'] + tokens[3:6]),
        16
    )

    # the bit inversion is required by the RFC
    return str(netaddr.IPAddress(network.value + (eui64 ^ 0x0200000000000000)))
