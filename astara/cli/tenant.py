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


"""Commands related to tenants.
"""
import logging

from astara import commands
from astara.cli import message


class _TenantCmd(message.MessageSending):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        p = super(_TenantCmd, self).get_parser(prog_name)
        p.add_argument(
            'tenant_id',
        )
        p.add_argument(
            '--reason',
        )
        return p

    def make_message(self, parsed_args):
        self.log.info(
            'sending %s instruction for tenant with uuid %r',
            self._COMMAND,
            parsed_args.tenant_id,
        )
        return {
            'command': self._COMMAND,
            'tenant_id': parsed_args.tenant_id,
            'reason': parsed_args.reason,
        }


class TenantDebug(_TenantCmd):
    """debug a single tenant"""

    _COMMAND = commands.TENANT_DEBUG


class TenantManage(_TenantCmd):
    """manage a single tenant"""

    _COMMAND = commands.TENANT_MANAGE
