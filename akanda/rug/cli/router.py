# Copyright 2014 DreamHost, LLC
#
# Author: DreamHost, LLC
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


"""Commands related to routers.
"""
from akanda.rug import commands
from akanda.rug.cli import message
from akanda.rug.api import nova

from novaclient import exceptions
from oslo.config import cfg
from neutronclient.v2_0 import client


class _TenantRouterCmd(message.MessageSending):

    def get_parser(self, prog_name):
        # Bypass the direct base class to let us put the tenant id
        # argument first
        p = super(_TenantRouterCmd, self).get_parser(prog_name)
        p.add_argument(
            'router_id',
        )
        return p

    def make_message(self, parsed_args):
        router_id = parsed_args.router_id.lower()
        if router_id == 'error':
            tenant_id = 'error'
        else:
            # Look up the tenant for a given router so we can send the
            # command using both and the rug can route it to the correct
            # worker. We do the lookup here instead of in the rug to avoid
            # having to teach the rug notification and dispatching code
            # about how to find the owner of a router, and to shift the
            # burden of the neutron API call to the client so the server
            # doesn't block. It also gives us a chance to report an error
            # when we can't find the router.
            n_c = client.Client(
                username=self.app.rug_ini.admin_user,
                password=self.app.rug_ini.admin_password,
                tenant_name=self.app.rug_ini.admin_tenant_name,
                auth_url=self.app.rug_ini.auth_url,
                auth_strategy=self.app.rug_ini.auth_strategy,
                auth_region=self.app.rug_ini.auth_region,
            )
            response = n_c.list_routers(router_id=router_id)
            try:
                router_details = response['routers'][0]
            except (KeyError, IndexError):
                raise ValueError('No router with id %r found: %s' %
                                 (router_id, response))
            tenant_id = router_details['tenant_id']
        self.log.info(
            'sending %s instruction for tenant %r, router %r',
            self._COMMAND,
            tenant_id,
            router_id,
        )
        return {
            'command': self._COMMAND,
            'router_id': router_id,
            'tenant_id': tenant_id,
        }


class RouterUpdate(_TenantRouterCmd):
    """force-update a router"""

    _COMMAND = commands.ROUTER_UPDATE


class RouterRebuild(_TenantRouterCmd):
    """force-rebuild a router"""

    _COMMAND = commands.ROUTER_REBUILD

    def get_parser(self, prog_name):
        p = super(RouterRebuild, self).get_parser(prog_name)
        p.add_argument(
            '--router_image_uuid',
        )
        return p

    def take_action(self, parsed_args):
        uuid = parsed_args.router_image_uuid
        if uuid:
            nova_client = nova.Nova(cfg.CONF).client
            try:
                nova_client.images.get(uuid)
            except exceptions.NotFound:
                self.log.exception(
                    'could not retrieve custom image %s from Glance:' % uuid
                )
                raise
        return super(RouterRebuild, self).take_action(parsed_args)

    def make_message(self, parsed_args):
        message = super(RouterRebuild, self).make_message(parsed_args)
        message['router_image_uuid'] = parsed_args.router_image_uuid
        return message


class RouterDebug(_TenantRouterCmd):
    """debug a single router"""

    _COMMAND = commands.ROUTER_DEBUG


class RouterManage(_TenantRouterCmd):
    """manage a single router"""

    _COMMAND = commands.ROUTER_MANAGE
