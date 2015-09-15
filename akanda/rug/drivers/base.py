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

    def synchronize_state(self, state):
        """sometimes a driver will need to update a service behind it with a new
        state.

        :param state: a valid state
        """
        pass

    def make_ports(self):
        """make ports call back for the nova client.

        :param _make_ports: a valid state
        """
        def _make_ports():
            pass

        return _make_ports

    @staticmethod
    def pre_populate_hook():
        """called in populate.py durring driver loading loop.
        """
        pass

    @staticmethod
    def get_resource_id_for_tenant(worker_context, tenant_id):
        """Find the id of a resource for a given tenant id

        :param tenant_id: The tenant uuid to search for

        :returns: uuid of the resource owned by the tenant
        """
