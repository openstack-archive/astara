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
                           help='image_uuid for router instances.'),

cfg.CONF.register_opts(ROUTER_CONFIG)


class Router(BaseDriver):

    RESOURCE_NAME = 'router'

    def boot(self):
        """

        :return:
        """
        pass

    def update_status(self, worker_context, status):
        """Updates status of logical resource

        :param worker_context:
        :param status:
        :returns: None
        """
        worker_context.neutron.update_router_status(self.id, status)

    def get_logical_config(self, worker_context):
        """static method gets logical config of the logical resource passed in

        :param worker_context:
        :returns: returns the logical config from neutron
        """
        return worker_context.neutron.get_router_detail(self.id)

    def build_config(self, worker_context, instance_info, meta):
        """Builds / rebuilds config

        :param worker_context:
        :param instance_info:
        :param meta:
        :returns: config object
        """
        return configuration.build_config(
            worker_context.neutron,
            worker_context.router,
            instance_info.management_port,
            meta
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
                worker_context.neutron.create_router_external_port()

    def pre_boot(self, worker_context):
        """pre-boot hook
        Calls self.pre_plug().

        :param worker_context:
        :return: None
        """
        self.pre_plug(worker_context)
