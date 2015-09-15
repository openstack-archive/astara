# Copyright (c) 2015 AKANDA, INC. All Rights Reserved.
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

from akanda.rug.api import configuration
from akanda.rug import event
from akanda.rug.api import neutron
from akanda.rug.drivers.base import BaseDriver
from akanda.rug.drivers import states
from akanda.rug.resource import Resource

from akanda.rug.common.i18n import _LW

LOG = logging.getLogger(__name__)

cfg.CONF.register_opts([
    cfg.StrOpt('router_image_uuid',
               help='image_uuid for router instances.'),
    cfg.IntOpt('router_instance_flavor',
               help='nova flavor to use for router instances')
])

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


def ensure_router_cache(f):
    def wrapper(self, worker_context):
        """updates local details object to current status and triggers
        neutron.RouterGone when the router is no longer available in neutron.

        :param worker_context:
        :returns: None
        """
        try:
            self.details = worker_context.neutron.get_router_detail(self.id)
        except neutron.RouterGone:
            self.details = None
    return wrapper


class Router(BaseDriver):

    RESOURCE_NAME = 'router'

    def post_init(self, worker_context):
        """Called at end of __init__ in BaseDriver.

        Populates the details object from neutron and sets image_uuid and
        flavor from cfg.

        :param worker_context:
        """
        self.image_uuid = cfg.CONF.router_image_uuid
        self.flavor = cfg.CONF.router_instance_flavor
        self._ensure_cache(worker_context)

    def _ensure_cache(self, worker_context):
        try:
            self.details = worker_context.neutron.get_router_detail(self.id)
        except neutron.RouterGone:
            self.details = None

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
            worker_context.neutron,
            self.details,
            mgt_port,
            iface_map
        )

    def pre_plug(self, worker_context):
        """pre-plug hook
        Sets up the external port.

        :param worker_context:
        :returs: None
        """
        if self.external_port is None:
            # FIXME: Need to do some work to pick the right external
            # network for a tenant.
            self.log.debug('Adding external port to router')
            self.external_port = \
                worker_context.neutron.create_router_external_port(self.details)

    def make_ports(self, worker_context):
        """make ports call back for the nova client.

        :param _make_ports: a valid state
        """
        def _make_ports():
            self._ensure_cache(worker_context)
            mgt_port = worker_context.neutron.create_management_port(
                self.id
            )

            # FIXME(mark): ideally this should be ordered and de-duped
            instance_ports = [
                worker_context.neutron.create_vrrp_port(self.id, n)
                for n in (p.network_id for p in self.details.ports)
            ]

            return mgt_port, instance_ports

        return _make_ports

    @staticmethod
    def pre_populate_hook():
        """Fetch the existing routers from neutrom then and returns list back
        to populate to be distributed to workers.

        Wait for neutron to return the list of the existing routers.
        Pause up to max_sleep seconds between each attempt and ignore
        neutron client exceptions.

        """
        nap_time = 1
        max_sleep = 15

        neutron_client = neutron.Neutron(cfg.CONF)

        while True:
            try:
                neutron_routers = neutron_client.get_routers(detailed=False)
                resources = []
                for router in neutron_routers:
                    resources.append(
                        Resource(driver=Router.RESOURCE_NAME,
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
                # FIXME(rods): should we get max_sleep from the config file?
                nap_time = min(nap_time * 2, max_sleep)


    @staticmethod
    def get_resource_id_for_tenant(worker_context, tenant_id):
        """Find the id of the router owned by tenant

        :param tenant_id: The tenant uuid to search for

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
        print 'xxx Processing router event for %s %s' % (event_type, payload)
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

        resource = Resource(driver='router',
                            id=router_id,
                            tenant_id=tenant_id)
        e = event.Event(
            resource=resource,
            crud=crud,
            body=payload,
        )
        print 'xxx Prepared router event: %s' % str(e)
        return e
