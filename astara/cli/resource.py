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
from astara.api import nova
from astara.cli import message
from astara import commands

from novaclient import exceptions
from oslo_config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class _TenantResourceCmd(message.MessageSending):

    def get_parser(self, prog_name):
        p = super(_TenantResourceCmd, self).get_parser(prog_name)
        p.add_argument(
            'resource_id',
        )
        p.add_argument(
            '--reason',
        )
        return p

    def make_message(self, parsed_args):
        resource_id = parsed_args.resource_id.lower()
        reason = parsed_args.reason
        self.log.info(
            'sending %s instruction for resource %r',
            self._COMMAND,
            resource_id,
        )
        return {
            'command': self._COMMAND,
            'resource_id': resource_id,
            'tenant_id': '*',
            'reason': reason,
        }


class ResourceUpdate(_TenantResourceCmd):
    """force-update a resource"""

    _COMMAND = commands.RESOURCE_UPDATE


class ResourceRebuild(_TenantResourceCmd):
    """force-rebuild a resource"""

    _COMMAND = commands.RESOURCE_REBUILD

    def get_parser(self, prog_name):
        p = super(ResourceRebuild, self).get_parser(prog_name)
        p.add_argument(
            '--image_uuid',
        )
        return p

    def take_action(self, parsed_args):
        uuid = parsed_args.image_uuid
        if uuid:
            nova_client = nova.Nova(cfg.CONF).client
            try:
                nova_client.images.get(uuid)
            except exceptions.NotFound:
                self.log.exception(
                    'could not retrieve custom image %s from Glance:' % uuid
                )
                raise
        return super(ResourceRebuild, self).take_action(parsed_args)

    def make_message(self, parsed_args):
        message = super(ResourceRebuild, self).make_message(parsed_args)
        message['resource_image_uuid'] = parsed_args.image_uuid
        return message


class ResourceDebug(_TenantResourceCmd):
    """debug a single resource"""

    _COMMAND = commands.RESOURCE_DEBUG


class ResourceManage(_TenantResourceCmd):
    """manage a single resource"""

    _COMMAND = commands.RESOURCE_MANAGE
