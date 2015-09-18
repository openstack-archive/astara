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


import netaddr

from oslo_log import log as logging

from akanda.rug.api.config import common

LOG = logging.getLogger(__name__)


def build_config(client, loadbalancer, management_port, iface_map):
    LOG.debug('Generating configuration for loadbalancer %s', loadbalancer.id)

    network_config = [
        common.network_config(
        client,
        loadbalancer.vip_port,
        iface_map[loadbalancer.vip_port.network_id],
        'loadbalancer'),

        common.network_config(
        client,
        management_port,
        iface_map[management_port.network_id],
        'management'),
    ]

    out = {
        'hostname': 'ak-loadbalancer-%s' % loadbalancer.tenant_id,
        'tenant_id': loadbalancer.tenant_id,
        'networks': network_config,
        'loadbalancer': {
            'name': loadbalancer.name,
            'id': loadbalancer.id,
        }
    }

    return out
