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
from akanda.rug.drivers.base import BaseDriver
from akanda.rug.api import configuration


class Router(BaseDriver):

    RESOURCE_NAME = 'Router'

    @staticmethod
    def update_status(worker_context, logical_obj, status):
        """Updates status of logical resource

        :param worker_context: worker_context object
        :param logical_obj: logical object
        :param status:
        :return: None
        """
        worker_context.neutron.update_router_status(logical_obj.id, status)

    @staticmethod
    def get_logical_config(worker_context, logical_id):
        """static method gets logical config of the logical resource passed in

        :param worker_context: worker_context object
        :param logical_id: id of logical resource
        :return: returns the logical config from neutron
        """
        return worker_context.neutron.get_router_detail(logical_id)

    @staticmethod
    def build_config(worker_context, logical_obj, instance_info, if_map):
        """Builds / rebuilds config

        :param worker_context:
        :param logical_obj:
        :param instance_info:
        :param if_map:
        :return: config object
        """
        return configuration.build_config(
            worker_context.neutron,
            logical_obj,
            instance_info.management_port,
            if_map
        )

    def pre_plug(self):
        """pre-plug hook
        Sets up the external port.

        :param worker_context:
        :param logical_obj:
        :return: None
        """
        if self.external_port is None:
            # FIXME: Need to do some work to pick the right external
            # network for a tenant.
            self.log.debug('Adding external port to router')
            self.external_port = \
                self.worker_context.neutron.create_router_external_port(
                    self
                )

    def pre_boot(self):
        """pre-boot hook
        Calls self.preplug().

        :return: None
        """
        self.preplug()
