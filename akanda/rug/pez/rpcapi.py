# Copyright 2015 Akanda, Inc
#
# Author: Akanda, Inc
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

from akanda.rug.common import rpc

from oslo_context import context


class AkandaPezAPI(object):
    """"Client side of the Akanda Pez RPC API.
    """
    def __init__(self, rpc_topic):
        self.topic = rpc_topic
        self.client = rpc.get_rpc_client(
            topic=self.topic)
        self.context =  context.get_admin_context().to_dict()

    def get_instance(self, resource_id, management_port, instance_ports):
        """Reserves an instance from the Pez service. We can instruct Pez to
        attach any required instance ports during the reservation process.
        The dict returned here should be enough for the caller to construct
        a InstanceInfo object.  Note that the port information are serialized
        akanda.rug.api.neutron.Port objects that can be deserialized by the
        caller during creation of InstanceInfo.

        :param resoruce_id: The uuid of the resource it will be used
                            for (ie, router id)
        :param managment_port: The management port dict that was created for
                               the instance by the RUG.
        :param instance_ports: A list of dicts of ports to be attached to
                               instance upon reservation.

        """
        cctxt = self.client.prepare(topic=self.topic)
        return cctxt.call(
            self.context, 'get_instance', resource_id=resource_id,
            management_port=management_port, instance_ports=instance_ports)
