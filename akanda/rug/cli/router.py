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
import logging

from akanda.rug import commands
from akanda.rug.cli import message


class _RouterCmd(message.MessageSending):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        p = super(_RouterCmd, self).get_parser(prog_name)
        p.add_argument(
            'router_id',
        )
        return p

    def make_message(self, parsed_args):
        self.log.info(
            'sending %s instruction for router with uuid %r',
            self._COMMAND,
            parsed_args.router_id,
        )
        return {
            'command': self._COMMAND,
            'router_id': parsed_args.router_id,
        }


class RouterDebug(_RouterCmd):
    """debug a single router"""

    _COMMAND = commands.ROUTER_DEBUG


class RouterManage(_RouterCmd):
    """manage a single router"""

    _COMMAND = commands.ROUTER_MANAGE


class _TenantRouterCmd(_RouterCmd):

    def get_parser(self, prog_name):
        # Bypass the direct base class to let us put the tenant id
        # argument first
        p = super(_RouterCmd, self).get_parser(prog_name)
        p.add_argument(
            'tenant_id',
        )
        p.add_argument(
            'router_id',
            nargs='?',
        )
        return p

    def make_message(self, parsed_args):
        self.log.info(
            'sending %s instruction for tenant %r, router with uuid %r',
            self._COMMAND,
            parsed_args.tenant_id,
            parsed_args.router_id,
        )
        return {
            'command': self._COMMAND,
            'router_id': parsed_args.router_id,
            'tenant_id': parsed_args.tenant_id,
        }


class RouterUpdate(_TenantRouterCmd):
    """force-update a router"""

    _COMMAND = commands.ROUTER_UPDATE


class RouterRebuild(_TenantRouterCmd):
    """force-rebuild a router"""

    _COMMAND = commands.ROUTER_REBUILD
