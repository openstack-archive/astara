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
from oslo_log import log as logging


class BaseDriver(object):

    RESOURCE_NAME = 'BaseDriver'

    def __init__(self, worker_context, id, log=None):
        """This is the abstract for rug drivers.

        :param id: logical resource id
        :param log: override default log
        """
        self.id = id
        self.external_port = None
        self.details = []
        self.flavor = None
        self.image_uuid = None
        self.name = 'ak-%s-%s' % (self.RESOURCE_NAME, self.id)

        if log:
            self.log = log
        else:
            self.log = logging.getLogger(self.name)

        self.post_init(worker_context)

    def post_init(self, worker_context):
        """post init hook

        :param worker_context:
        :returns: None
        """
        pass

    def pre_boot(self, worker_context):
        """pre boot hook

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

    def update_state(self, worker_context, silent=False):
        """returns state of logical resource.

        :param worker_context:
        :param silent:
        :returns: None
        """
        pass

    def build_config(self, worker_context, mgt_port, iface_map):
        """gets config of logical resource attached to worker_context.

        :param worker_context:
        :returns: None
        """
        pass

    def update_config(self,  management_address, config):
        """Updates appliance configuratino

        This is responsible for pushing configuration to the managed
        appliance
        """
        pass

    def synchronize_state(self, worker_context, state):
        """sometimes a driver will need to update a service behind it with a
        new state.

        :param state: a valid state
        """
        pass

    def make_ports(self, worker_context):
        """Make ports call back for the nova client.

        This is expected to create the management port for the instance
        and any required instance ports.

        :param worker_context:

        :returns: A tuple (managment_port, [instance_ports])
        """
        def _make_ports():
            pass

        return _make_ports

    def delete_ports(self, worker_context):
        """Delete all created ports.

        :param worker_context:
        :returns: None
        """

    @staticmethod
    def pre_populate_hook():
        """called in populate.py durring driver loading loop.
        """
        pass

    def pre_plug(self, worker_context):
        """pre-plug hook

        :param worker_context:
        :returns: None
        """

    @staticmethod
    def get_resource_id_for_tenant(worker_context, tenant_id, message):
        """Find the id of a resource for a given tenant id and message.

        For some resources simply searching by tenant_id is enough, for
        others some context from the message payload may be necessary.

        :param worker_context: A worker context with instantiated clients
        :param tenant_id: The tenant uuid to search for
        :param message: The message associated with the request

        :returns: uuid of the resource owned by the tenant
        """
        pass

    @staticmethod
    def process_notification(tenant_id, event_type, payload):
        """Process an incoming notification event

        This gets called from the notifications layer to determine whether
        a driver should process an incoming notification event. It is
        responsible for translating an incoming notification to an Event
        object appropriate for that driver.

        :param tenant_id: str The UUID tenant_id for the incoming event
        :param event_type: str event type, for example router.create.end
        :param payload: The payload body of the incoming event

        :returns: A populated Event objet if it should process, or None if not
        """
        pass

    @property
    def ports(self):
        """Lists ports associated with the resource.

        :returns: A list of astara.api.neutron.Port objects or []
        """

    def get_interfaces(self, management_address):
        """Lists interfaces attached to the resource.

        This lists the interfaces attached to the resource from the POV
        of the resource iteslf.

        :returns: A list of interfaces
        """
        pass

    def is_alive(self, management_address):
        """Determines whether the managed resource is alive

        :returns: bool True if alive, False if not
        """

    def get_state(self, worker_context):
        """Returns the state of the managed resource"""

    def rebalance_takeover(self, worker_context):
        """Complete any post-rebalance takeover actions

        Used to run driver-specific actions to be completed when a
        cluster rebalance event migrates management of the appliance
        to a new orchestrator worker.  This can be used, for example,
        to inform a router appliance of the local orchestrator's management
        address for purposes of metadata proxying.

        :param worker_context:
        """
