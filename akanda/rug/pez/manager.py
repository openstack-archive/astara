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

    # NOTE(adam_g): We should consider how these get configured for when
    #               we support multiple drivers. {router, lbaas}_image_uuid?
    cfg.StrOpt('image_uuid',
               help=_('Image uuid to boot.')),
    cfg.StrOpt('flavor',
               help=_('Nova flavor to boot')),
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

    def get_instance(self, context, resource_type, name, management_port,
                     instance_ports):
        """Obtains an instance from the pool for client

        This obtains an instance from the pool manager  and returns enough data
        about it to the client that the client can create an InstanceInfo
        object.  We purposely avoid the need to introduce versioned object (for
        now) by serializing everything into a dict.  This may change in the
        future.

        :param context: oslo_context admin context object
        :param resource_type: The str driver name of the resource
        :param name: The requested name of the instance
        :param managment_port: The management port dict that was created for
                               the instance by the RUG.
        :param instance_ports: A list of dicts of ports to be attached to
                               instance upon reservation.

        :returns: A dict containing the following:
                    - 'id': The id of the reserved instance
                    - 'name': The name of the reserved instance
                    - 'image_uuid': The image id of the reserved instance
                    - 'management_port': A serialized dict representing the
                                         management Neutron port.
                    - 'instance_port': A list of serialized instance port
                                       dicts that the caller requested be
                                       attached.

        """
        instance, mgt_port, instance_ports = self.pool_mgr.get_instance(
            resource_type=resource_type, name=name,
            management_port=management_port, instance_ports=instance_ports)

        return {
            'id': instance.id,
            'resource_type': resource_type,
            'name': instance.name,
            'image_uuid': instance.image['id'],
            'management_port': mgt_port.to_dict(),
            'instance_ports': [
                p.to_dict() for p in instance_ports
            ],
        }
