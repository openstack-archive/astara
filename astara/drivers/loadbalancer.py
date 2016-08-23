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

from neutronclient.common import exceptions as q_exceptions

from astara.api import astara_client
from astara.api.config import loadbalancer as config
from astara.api import neutron
from astara.common.i18n import _, _LW
from astara.drivers.base import BaseDriver
from astara.drivers import states
from astara import event

LOG = logging.getLogger(__name__)


LOADBALANCER_OPTS = [
    cfg.StrOpt('image_uuid',
               help='The image_uuid for loadbalancer instances.'),
    cfg.StrOpt('instance_flavor',
               help='The nova flavor id to use for loadbalancer instances'),
    cfg.IntOpt('mgt_service_port', default=5000,
               help='The port on which the loadbalancer API service listens '
                    'on loadbalancer appliances'),
]
cfg.CONF.register_group(cfg.OptGroup(name='loadbalancer'))
cfg.CONF.register_opts(LOADBALANCER_OPTS, 'loadbalancer')


STATUS_MAP = {
    states.DOWN: neutron.PLUGIN_DOWN,
    states.BOOTING: neutron.PLUGIN_PENDING_CREATE,
    states.UP: neutron.PLUGIN_PENDING_CREATE,
    states.CONFIGURED: neutron.PLUGIN_ACTIVE,
    states.ERROR: neutron.PLUGIN_ERROR,
    states.REPLUG: neutron.PLUGIN_PENDING_UPDATE,
}


class LoadBalancer(BaseDriver):

    RESOURCE_NAME = 'loadbalancer'
    _last_synced_status = None

    def post_init(self, worker_context):
        """Called at end of __init__ in BaseDriver.

        Populates the details object from neutron and sets image_uuid and
        flavor from cfg.

        :param worker_context:
        """
        self.image_uuid = cfg.CONF.loadbalancer.image_uuid
        self.flavor = cfg.CONF.loadbalancer.instance_flavor
        self.mgt_port = cfg.CONF.loadbalancer.mgt_service_port

        self._ensure_cache(worker_context)

    def _ensure_cache(self, worker_context):
        try:
            lb = worker_context.neutron.get_loadbalancer_detail(self.id)
            self._loadbalancer = lb
        except neutron.LoadBalancerGone:
            self._loadbalancer = None

    @property
    def ports(self):
        """Lists ports associated with the resource.

        :returns: A list of astara.api.neutron.Port objects or []
        """
        if self._loadbalancer:
            return [p for p in self._loadbalancer.ports]
        else:
            return []

    def pre_boot(self, worker_context):
        """pre boot hook
        Calls self.pre_plug().

        :param worker_context:
        :returns: None
        """
        pass

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
        return config.build_config(
            worker_context.neutron,
            self._loadbalancer,
            mgt_port,
            iface_map)

    def update_config(self, management_address, config):
        """Updates appliance configuration

        This is responsible for pushing configuration to the managed
        appliance
        """
        self.log.info(_('Updating config for %s'), self.name)
        astara_client.update_config(management_address, self.mgt_port, config)

    def pre_plug(self, worker_context):
        """pre-plug hook
        Sets up the external port.

        :param worker_context:
        :returs: None
        """

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

            # allocate a port on the same net as the LB VIP
            lb_port = worker_context.neutron.create_vrrp_port(
                object_id=self.id,
                network_id=self._loadbalancer.vip_port.network_id,
                label='LB',
            )

            return mgt_port, [lb_port]

        return _make_ports

    def delete_ports(self, worker_context):
        """Delete all ports.

        :param worker_context:
        :returns: None

        """
        worker_context.neutron.delete_vrrp_port(self.id, label='LB')
        worker_context.neutron.delete_vrrp_port(self.id, label='MGT')

    @staticmethod
    def pre_populate_hook():
        """Fetch the existing LBs from neutron then and returns list back
        to populate to be distributed to workers.

        Wait for neutron to return the list of the existing LBs.
        Pause up to max_sleep seconds between each attempt and ignore
        neutron client exceptions.

        """
        nap_time = 1

        neutron_client = neutron.Neutron(cfg.CONF)

        while True:
            try:
                resources = []
                for lb in neutron_client.get_loadbalancers():
                    resources.append(
                        event.Resource(driver=LoadBalancer.RESOURCE_NAME,
                                       id=lb.id,
                                       tenant_id=lb.tenant_id))

                return resources
            except (q_exceptions.Unauthorized, q_exceptions.Forbidden) as err:
                LOG.warning(_LW('PrePopulateWorkers thread failed: %s'), err)
                return
            except Exception as err:
                LOG.warning(
                    _LW('Could not fetch loadbalancers from neutron: %s'), err)
                LOG.warning(_LW(
                    'sleeping %s seconds before retrying'), nap_time)
                time.sleep(nap_time)
                nap_time = min(nap_time * 2,
                               cfg.CONF.astara_appliance.max_sleep)

    @staticmethod
    def get_resource_id_for_tenant(worker_context, tenant_id, message):
        """Find the id of the loadbalancer owned by tenant

        Some events (ie, member.create.end) give us no context about which
        LB the event is associated and only show us the tenant_id and member
        id, so we for those we need to some resolution here.

        :param tenant_id: The tenant uuid to search for
        :param message: Message associated /w the request

        :returns: uuid of the loadbalancer owned by the tenant
        """

        lb_id = None

        # loadbalancer.create.end contains the id in the payload
        if message.body.get('loadbalancer'):
            lb_id = message.body['loadbalancer'].get('id')
        # listener.create.end references the loadbalancer directly
        elif message.body.get('listener'):
            lb_id = message.body['listener'].get('loadbalancer_id')
        # pool.create.end references by listener
        elif message.body.get('pool'):
            listener_id = message.body['pool'].get('listener_id')
            if listener_id:
                lb = worker_context.neutron.get_loadbalancer_by_listener(
                    listener_id, tenant_id)
                if lb:
                    lb_id = lb.id
        # member.crate.end only gives us the member id itself.
        elif message.body.get('member') or message.body.get('member_id'):
            member_id = (message.body.get('member', {}).get('id') or
                         message.body.get('member_id'))
            if member_id:
                lb = worker_context.neutron.get_loadbalancer_by_member(
                    member_id=member_id, tenant_id=tenant_id)
                if lb:
                    lb_id = lb.id
        return lb_id

    @staticmethod
    def process_notification(tenant_id, event_type, payload):
        """Process an incoming notification event

        This gets called from the notifications layer to determine whether
        this driver should process an incoming notification event. It is
        responsible for translating an incoming notificatino to an Event
        object appropriate for this driver.

        :param tenant_id: str The UUID tenant_id for the incoming event
        :param event_type: str event type, for example loadbalancer.create.end
        :param payload: The payload body of the incoming event

        :returns: A populated Event objet if it should process, or None if not
        """
        if event_type.startswith('loadbalancerstatus.update'):
            # these are generated when we sync state
            return
        lb_id = (
            payload.get('loadbalancer', {}).get('id') or
            payload.get('listener', {}).get('loadbalancer_id') or
            payload.get('loadbalancer_id')
        )

        update_notifications = [
            'listener.create.start',
            'pool.create.start',
            'member.create.end',
            'member.delete.end',
        ]

        # some events do not contain a lb id.
        if not lb_id and event_type not in update_notifications:
            return

        if event_type == 'loadbalancer.create.end':
            crud = event.CREATE
        elif event_type == 'loadbalancer.delete.end':
            crud = event.DELETE
        elif event_type in update_notifications:
            crud = event.UPDATE
        else:
            crud = None

        if not crud:
            LOG.info('Could not determine CRUD for event: %s ', event_type)
            return

        resource = event.Resource(driver=LoadBalancer.RESOURCE_NAME,
                                  id=lb_id,
                                  tenant_id=tenant_id)
        e = event.Event(
            resource=resource,
            crud=crud,
            body=payload,
        )
        return e

    def get_state(self, worker_context):
        self._ensure_cache(worker_context)
        if not self._loadbalancer:
            return states.GONE
        else:
            # NOTE(adam_g): We probably want to map this status back to
            # an internal astara status
            return self._loadbalancer.status

    def synchronize_state(self, worker_context, state):
        self._ensure_cache(worker_context)
        if not self._loadbalancer:
            LOG.debug('Not synchronizing state with missing loadbalancer %s',
                      self.id)
            return

        new_status = STATUS_MAP.get(state)
        old_status = self._last_synced_status
        LOG.debug('Synchronizing loadbalancer %s state %s->%s',
                  self.id, old_status, new_status)
        worker_context.neutron.update_loadbalancer_status(
            self.id, new_status)
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
