# Copyright 2015 Akanda, Inc.
#
# Author: Akanda, Inc.
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


class GlobalDebug(message.MessageSending):
    """Enable or disable global debug mode"""

    _COMMAND = commands.GLOBAL_DEBUG

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        p = super(GlobalDebug, self).get_parser(prog_name)
        p.add_argument(
            'status',
        )
        p.add_argument(
            '--reason',
        )
        return p

    def make_message(self, parsed_args):
        status = parsed_args.status.lower()
        if status not in ['enable', 'disable']:
            m = "Invalid global-debug command, must 'enable' or 'disable'"
            raise ValueError(m)

        self.log.info(
            "sending instruction to %s global debug mode" % status
        )
        return {
            'command': self._COMMAND,
            'enabled': 1 if status == "enable" else 0,
            'reason': parsed_args.reason,
        }
