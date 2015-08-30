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
from oslo_config import cfg
from akanda.rug.api import configuration
from akanda.rug.api import neutron
from akanda.rug.drivers.base import BaseDriver
from akanda.rug.drivers import states

ROUTER_CONFIG = [cfg.IntOpt('router_image_uuid',
                            help='image_uuid for router instances.'),
                 cfg.IntOpt('router_flavor',
                            help='nova flavor to use for router instances'), ]

cfg.CONF.register_opts(ROUTER_CONFIG)

STATUS_MAP = {
    states.DOWN: neutron.STATUS_DOWN,
    states.BOOTING: neutron.STATUS_BUILD,
    states.UP: neutron.STATUS_BUILD,
    states.CONFIGURED: neutron.STATUS_ACTIVE,
    states.ERROR: neutron.STATUS_ERROR,
}


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
            # The router has been deleted, set our state accordingly
            # and return without doing any more work.
            self.state = self.GONE
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
        self.flavor = cfg.CONF.router_flavor
        self.details = worker_context.neutron.get_router_detail(self.id)

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

    @ensure_router_cache
    def build_config(self, worker_context, mgt_port, iface_map):
        """Builds / rebuilds config

        :param worker_context:
        :param mgt_port:
        :param iface_map:
        :returns: configuration object
        """
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
                worker_context.neutron.create_router_external_port()
