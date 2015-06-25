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
from oslo_config import cfg


ROUTER_CONFIG = cfg.IntOpt('router_image_uuid',
                           default='abc',
                           help='image_uuid for router instances.'),

cfg.CONF.register_opts(ROUTER_CONFIG)


class Router(BaseDriver):

    RESOURCE_NAME = 'router'

    def boot(self):
        """

        :return:
        """
        pass

    def update_status(self, status):
        """Updates status of logical resource

        :param status:
        :return: None
        """
        self.worker_context.neutron.update_router_status(self.id, status)

    def get_logical_config(self):
        """static method gets logical config of the logical resource passed in

        :return: returns the logical config from neutron
        """
        return self.worker_context.neutron.get_router_detail(self.id)

    def build_config(self, instance_info, meta):
        """Builds / rebuilds config

        :param instance_info:
        :param meta:
        :return: config object
        """
        return configuration.build_config(
            self.worker_context.neutron,
            self,
            instance_info.management_port,
            meta
        )

    def pre_plug(self):
        """pre-plug hook
        Sets up the external port.

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
        Calls self.pre_plug().

        :return: None
        """
        self.pre_plug()
