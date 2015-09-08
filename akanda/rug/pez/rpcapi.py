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
from akanda.rug.pez.manager import RPC_TOPIC

from oslo_context import context


class AkandaPezAPI(object):
    """"Client side of the Akanda Pez RPC API.
    """
    def __init__(self):
        self.topic = RPC_TOPIC
        self.client = rpc.get_rpc_client(
            topic=self.topic)
        self.context =  context.get_admin_context().to_dict()

    def list_instances(self):
        cctxt = self.client.prepare(topic=self.topic)
        return cctxt.call(self.context, 'list_instances')
