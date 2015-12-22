# Copyright (c) 2015 Akanda, Inc. All Rights Reserved.
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
import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from neutronclient.common import exceptions as q_exceptions

from astara.common.i18n import _
from astara.api import astara_client
from astara.api.config import router as configuration
from astara import event
from astara.api import neutron
from astara.drivers.base import BaseDriver
from astara.drivers import states
from astara.common.i18n import _LW

LOG = logging.getLogger(__name__)


ROUTER_OPTS = [
    cfg.StrOpt('image_uuid',
               help='The image_uuid for router instances.',
               deprecated_opts=[
                    cfg.DeprecatedOpt('router_image_uuid',
                                      group='DEFAULT')]),
    cfg.StrOpt('instance_flavor',
               help='The nova id flavor to use for router instances',
               deprecated_opts=[
                    cfg.DeprecatedOpt('router_instance_flavor',
                                      group='DEFAULT')]),
    cfg.IntOpt('mgt_service_port', default=5000,
               help='The port on which the router API service listens on '
                    'router appliances',
               deprecated_opts=[
                    cfg.DeprecatedOpt('akanda_mgt_service_port',
                                      group='DEFAULT')]),
]
cfg.CONF.register_group(cfg.OptGroup(name='router'))
cfg.CONF.register_opts(ROUTER_OPTS, 'router')


STATUS_MAP = {
    states.DOWN: neutron.STATUS_DOWN,
    states.BOOTING: neutron.STATUS_BUILD,
    states.UP: neutron.STATUS_BUILD,
    states.CONFIGURED: neutron.STATUS_ACTIVE,
    states.ERROR: neutron.STATUS_ERROR,
}


_ROUTER_INTERFACE_NOTIFICATIONS = set([
    'router.interface.create',
    'router.interface.delete',
])

_ROUTER_INTERESTING_NOTIFICATIONS = set([
    'subnet.create.end',
    'subnet.change.end',
    'subnet.delete.end',
    'port.create.end',
    'port.change.end',
    'port.delete.end',
])


DRIVER_NAME = 'router'


class Router(BaseDriver):

    RESOURCE_NAME = DRIVER_NAME
    _last_synced_status = None

    def post_init(self, worker_context):
        """Called at end of __init__ in BaseDriver.

        Populates the _router object from neutron and sets image_uuid and
        flavor from cfg.

        :param worker_context:
        """
        self.image_uuid = cfg.CONF.router.image_uuid
        self.flavor = cfg.CONF.router.instance_flavor
        self.mgt_port = cfg.CONF.router.mgt_service_port

        self._ensure_cache(worker_context)

    def _ensure_cache(self, worker_context):
        try:
            self._router = worker_context.neutron.get_router_detail(self.id)
        except neutron.RouterGone:
            self._router = None

    @property
    def ports(self):
        """Lists ports associated with the resource.

        :returns: A list of astara.api.neutron.Port objects or []
        """
        if self._router:
            return [p for p in self._router.ports]
        else:
            return []

    def pre_boot(self, worker_context):
        """pre boot hook
        Calls self.pre_plug().

        :param worker_context:
        :returns: None
        """
        self.pre_plug(worker_context)

    def post_boot(self, worker_context):
        """post boot hook

        :param worker_context:
        :returns: None
        """
        pass

    def build_config(self, worker_context, mgt_port, iface_map):
        """Builds / rebuilds config

        :param worker_context:
        :param mgt_port:
        :param iface_map:
        :returns: configuration object
        """
        self._ensure_cache(worker_context)
        return configuration.build_config(
            worker_context,
            self._router,
            mgt_port,
            iface_map
        )

    def update_config(self, management_address, config):
        """Updates appliance configuration

        This is responsible for pushing configuration to the managed
        appliance
        """
        self.log.info(_('Updating config for %s'), self.name)
        start_time = timeutils.utcnow()

        astara_client.update_config(
            management_address, self.mgt_port, config)
        delta = timeutils.delta_seconds(start_time, timeutils.utcnow())
        self.log.info(_('Config updated for %s after %s seconds'),
                      self.name, round(delta, 2))

    def pre_plug(self, worker_context):
        """pre-plug hook
        Sets up the external port.

        :param worker_context:
        :returs: None
        """
        if self._router.external_port is None:
            # FIXME: Need to do some work to pick the right external
            # network for a tenant.
            self.log.debug('Adding external port to router %s')
            ext_port = worker_context.neutron.create_router_external_port(
                self._router)
            self._router.external_port = ext_port

    def make_ports(self, worker_context):
        """make ports call back for the nova client.

        :param worker_context:

        :returns: A tuple (managment_port, [instance_ports])
        """
        def _make_ports():
            self._ensure_cache(worker_context)
            mgt_port = worker_context.neutron.create_management_port(
                self.id
            )

            # FIXME(mark): ideally this should be ordered and de-duped
            instance_ports = [
                worker_context.neutron.create_vrrp_port(self.id, n)
                for n in (p.network_id for p in self._router.ports)
            ]

            return mgt_port, instance_ports

        return _make_ports

    def delete_ports(self, worker_context):
        """Delete all ports.

        :param worker_context:
        :returns: None

        """
        worker_context.neutron.delete_vrrp_port(self.id)
        worker_context.neutron.delete_vrrp_port(self.id, label='MGT')

    @staticmethod
    def pre_populate_hook():
        """Fetch the existing routers from neutrom then and returns list back
        to populate to be distributed to workers.

        Wait for neutron to return the list of the existing routers.
        Pause up to max_sleep seconds between each attempt and ignore
        neutron client exceptions.

        """
        nap_time = 1

        neutron_client = neutron.Neutron(cfg.CONF)

        while True:
            try:
                neutron_routers = neutron_client.get_routers(detailed=False)
                resources = []
                for router in neutron_routers:
                    resources.append(
                        event.Resource(driver=DRIVER_NAME,
                                       id=router.id,
                                       tenant_id=router.tenant_id)
                    )

                return resources
            except (q_exceptions.Unauthorized, q_exceptions.Forbidden) as err:
                LOG.warning(_LW('PrePopulateWorkers thread failed: %s'), err)
                return
            except Exception as err:
                LOG.warning(
                    _LW('Could not fetch routers from neutron: %s'), err)
                LOG.warning(_LW(
                    'sleeping %s seconds before retrying'), nap_time)
                time.sleep(nap_time)
                nap_time = min(nap_time * 2,
                               cfg.CONF.astara_appliance.max_sleep)

    @staticmethod
    def get_resource_id_for_tenant(worker_context, tenant_id, message):
        """Find the id of the router owned by tenant

        :param tenant_id: The tenant uuid to search for
        :param message: message associated /w request (unused here)

        :returns: uuid of the router owned by the tenant
        """
        router = worker_context.neutron.get_router_for_tenant(tenant_id)
        if not router:
            LOG.debug('Router not found for tenant %s.',
                      tenant_id)
            return None
        return router.id

    @staticmethod
    def process_notification(tenant_id, event_type, payload):
        """Process an incoming notification event

        This gets called from the notifications layer to determine whether
        this driver should process an incoming notification event. It is
        responsible for translating an incoming notificatino to an Event
        object appropriate for this driver.

        :param tenant_id: str The UUID tenant_id for the incoming event
        :param event_type: str event type, for example router.create.end
        :param payload: The payload body of the incoming event

        :returns: A populated Event objet if it should process, or None if not
        """
        router_id = payload.get('router', {}).get('id')
        crud = event.UPDATE

        if event_type.startswith('routerstatus.update'):
            # We generate these events ourself, so ignore them.
            return

        if event_type == 'router.create.end':
            crud = event.CREATE
        elif event_type == 'router.delete.end':
            crud = event.DELETE
            router_id = payload.get('router_id')
        elif event_type in _ROUTER_INTERFACE_NOTIFICATIONS:
            crud = event.UPDATE
            router_id = payload.get('router.interface', {}).get('id')
        elif event_type in _ROUTER_INTERESTING_NOTIFICATIONS:
            crud = event.UPDATE
        elif event_type.endswith('.end'):
            crud = event.UPDATE
        else:
            LOG.debug('Not processing event: %s' % event_type)
            return

        resource = event.Resource(driver=DRIVER_NAME,
                                  id=router_id,
                                  tenant_id=tenant_id)
        e = event.Event(
            resource=resource,
            crud=crud,
            body=payload,
        )
        return e

    def get_state(self, worker_context):
        self._ensure_cache(worker_context)
        if not self._router:
            return states.GONE
        else:
            # NOTE(adam_g): We probably want to map this status back to
            # an internal astara status
            return self._router.status

    def synchronize_state(self, worker_context, state):
        self._ensure_cache(worker_context)
        if not self._router:
            LOG.debug('Not synchronizing state with missing router %s',
                      self.id)
            return
        new_status = STATUS_MAP.get(state)
        old_status = self._last_synced_status
        if not old_status or old_status != new_status:
            LOG.debug('Synchronizing router %s state %s->%s',
                      self.id, old_status, new_status)
            worker_context.neutron.update_router_status(self.id, new_status)
            self._last_synced_status = new_status

    def get_interfaces(self, management_address):
        """Lists interfaces attached to the resource.

        This lists the interfaces attached to the resource from the POV
        of the resource iteslf.

        :returns: A list of interfaces
        """
        return astara_client.get_interfaces(management_address,
                                            self.mgt_port)

    def is_alive(self, management_address):
        """Determines whether the managed resource is alive

        :returns: bool True if alive, False if not
        """
        return astara_client.is_alive(management_address, self.mgt_port)

    def rebalance_takeover(self, worker_context, management_address, config):
        """Complete any post-rebalance takeover actions

        Used to run driver-specific actions to be completed when a
        cluster rebalance event migrates management of the appliance
        to a new orchestrator worker.  This can be used, for example,
        to inform a router appliance of the local orchestrator's management
        address for purposes of metadata proxying.

        :param worker_context:
        """
        LOG.debug('Updating router configuration for %s after post-rebalance '
                  'takeover', self.id)
        return self.update_config(management_address, config)
