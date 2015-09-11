# Copyright 2015 Akanda, Inc
#
# Author: Akanda, Inc
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


import threading

from akanda.rug.pez import pool
from akanda.rug.common.i18n import _

from oslo_config import cfg

CONF = cfg.CONF

PEZ_OPTIONS = [
    cfg.IntOpt('pool_size', default=1,
               help=_('How many pre-allocated hot standby nodes to keep '
                      'in the pez pool.')),
    cfg.StrOpt('image_uuid',
               help=_('Image uuid to boot XXX')),
    cfg.StrOpt('flavor',
               help=_('Nova flavor to boot XXX')),
    cfg.StrOpt('rpc_topic', default='akanda-pez'),

]
CONF.register_group(cfg.OptGroup(name='pez'))
CONF.register_opts(PEZ_OPTIONS, group='pez')


CONF.import_opt('host', 'akanda.rug.main')
CONF.import_opt('management_network_id', 'akanda.rug.api.neutron')


class PezManager(object):
    """The RPC server-side of the Pez service"""
    def __init__(self):
        self.image_uuid = CONF.pez.image_uuid
        self.flavor = CONF.pez.flavor
        self.mgt_net_id = CONF.management_network_id
        self.pool_size = CONF.pez.pool_size
        self.pool_mgr = pool.PezPoolManager(
            self.image_uuid,
            self.flavor,
            self.pool_size,
            self.mgt_net_id)

    def start(self):
        pooler_thread = threading.Thread(target=self.pool_mgr.start)
        pooler_thread.start()

    def get_instance(self, context, resource_id, management_port,
                     instance_ports):
        instance = self.pool_mgr.get_instance(
            resource_id=resource_id, management_port=management_port,
            instance_ports=instance_ports)
        return {
            'id': instance.id,
            'name': instance.name,
            'image_uuid': instance.image['id']
        }
