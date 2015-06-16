# Copyright 2015 Akanda inc.
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
from akanda.rug.api import configuration
from oslo.config import cfg


class InstanceDriver(object):
    """This is the abstract for any akanda-rug driver"""
    RESOURCE_NAME = 'unknown'

    def __init__(self, image_uuid, log):
        self.image_uuid = image_uuid
        self.log = log

    def get_logical_config(self, worker_context, logical_id):
        return None

    def preboot(self, worker_context, logical_obj):
        pass

    def preplug(self, worker_context, logical_obj):
        pass

    def update_status(self, worker_context, logical_obj, status):
        pass

    def build_config(self, worker_context, logical_obj, instance_info, if_map):
        pass

    @property
    def default_image_uuid(self):
        return None


class RouterDriver(InstanceDriver):
    """Router driver code"""
    RESOURCE_NAME = 'Router'

    def get_logical_config(self, worker_context, logical_id):
        """returns the logical config from neutron"""
        return worker_context.neutron.get_router_detail(logical_id)

    def preplug(self, worker_context, logical_obj):
        if logical_obj.external_port is None:
            # FIXME: Need to do some work to pick the right external
            # network for a tenant.
            self.log.debug('Adding external port to router')
            ext_port = worker_context.neutron.create_router_external_port(
                logical_obj
            )
            logical_obj.external_port = ext_port

    preboot = preplug

    def update_status(self, worker_context, logical_obj, status):
        worker_context.neutron.update_router_status(logical_obj.id, status)

    def build_config(self, worker_context, logical_obj, instance_info, if_map):
        return configuration.build_config(
            worker_context.neutron,
            logical_obj,
            instance_info.management_port,
            if_map
        )

    @property
    def default_image_uuid(self):
        return cfg.CONF.router_image_uuid


options = {'router': RouterDriver}
