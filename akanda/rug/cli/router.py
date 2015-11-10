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
import argparse
import subprocess
import sys

from akanda.rug.common.i18n import _LW
from akanda.rug import commands
from akanda.rug.cli import message
from akanda.rug.api import keystone, nova, neutron

from novaclient import exceptions
from oslo_config import cfg
from oslo_log import log as logging

from neutronclient.v2_0 import client


LOG = logging.getLogger(__name__)


class _TenantRouterCmd(message.MessageSending):

    def get_parser(self, prog_name):
        new_cmd = str(prog_name).replace('router', 'resource')
        LOG.warning(_LW(
            "WARNING: '%s' is deprecated in favor of '%s' and will be removed "
            "in the Mitaka release.") % (prog_name, new_cmd))
        # Bypass the direct base class to let us put the tenant id
        # argument first
        p = super(_TenantRouterCmd, self).get_parser(prog_name)
        p.add_argument(
            'router_id',
        )
        p.add_argument(
            '--reason',
        )
        return p

    def make_message(self, parsed_args):
        router_id = parsed_args.router_id.lower()
        reason = parsed_args.reason
        if router_id == 'error':
            tenant_id = 'error'
        elif router_id == '*':
            tenant_id = '*'
        else:
            # Look up the tenant for a given router so we can send the
            # command using both and the rug can route it to the correct
            # worker. We do the lookup here instead of in the rug to avoid
            # having to teach the rug notification and dispatching code
            # about how to find the owner of a router, and to shift the
            # burden of the neutron API call to the client so the server
            # doesn't block. It also gives us a chance to report an error
            # when we can't find the router.
            ks_session = keystone.KeystoneSession()
            n_c = client.Client(session=ks_session.session)
            response = n_c.list_routers(retrieve_all=True, id=router_id)
            try:
                router_details = response['routers'][0]
            except (KeyError, IndexError):
                raise ValueError('No router with id %r found: %s' %
                                 (router_id, response))
            assert router_details['id'] == router_id
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
            'reason': reason,
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


class RouterSSH(_TenantRouterCmd):
    """ssh into a router over the management network"""

    interactive = True

    def get_parser(self, prog_name):
        p = super(RouterSSH, self).get_parser(prog_name)
        p.add_argument('remainder', nargs=argparse.REMAINDER)
        return p

    def take_action(self, parsed_args):
        ks_session = keystone.KeystoneSession()
        n_c = client.Client(session=ks_session.session)
        router_id = parsed_args.router_id.lower()
        ports = n_c.show_router(router_id).get('router', {}).get('ports', {})
        for port in ports:
            if port['fixed_ips'] and \
               port['device_owner'] == neutron.DEVICE_OWNER_ROUTER_MGT:
                v6_addr = port['fixed_ips'].pop()['ip_address']
                try:
                    cmd = ["ssh", "root@%s" % v6_addr] + parsed_args.remainder
                    subprocess.check_call(cmd)
                except subprocess.CalledProcessError as e:
                    sys.exit(e.returncode)
