# Copyright (c) 2015 Akanda, Inc. All Rights Reserved.
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

import mock

from akanda.rug.drivers import base
from akanda.rug.api import neutron, nova
from akanda.rug import worker


def fake_router():
    router_gateway_port = {
        'id': 'ext',
        'name': 'router_gateway_port',
        'device_id': 'device_id',
        'fixed_ips': [],
        'mac_address': 'aa:bb:cc:dd:ee:ff',
        'network_id': 'net_id',
        'device_owner': 'network:router_gateway'
    }
    router_internal_port = {
        'id': 'ext',
        'name': 'router_internal_port',
        'device_id': 'device_id',
        'fixed_ips': [],
        'mac_address': 'aa:bb:cc:dd:ee:ff',
        'network_id': 'net_id',
        'device_owner': 'network:router_interface'
    }

    router_fip = {
        'id': 'fip',
        'floating_ip_address': '9.9.9.9',
        'fixed_ip_address': '192.168.1.1'
    }

    router_dict = {
        'id': '1',
        'tenant_id': 'tenant_id',
        'name': 'name',
        'admin_state_up': True,
        'status': 'ACTIVE',
        'gw_port': router_gateway_port,
        '_interfaces': [router_internal_port],
        '_floatingips': [router_fip]
    }
    return neutron.Router.from_dict(router_dict)


def fake_driver(resource_id=None):
    """A factory for generating fake driver instances suitable for testing"""
    fake_driver = mock.Mock(base.BaseDriver, autospec=True)
    fake_driver.RESOURCE_NAME = 'FakeDriver'
    fake_driver.id = resource_id or 'fake_resource_id'
    fake_driver.log = mock.Mock()
    fake_driver.flavor = 'fake_flavor'
    fake_driver.name = 'ak-FakeDriver-fake_resource_id'
    fake_driver.image_uuid = 'fake_image_uuid'
    fake_driver.make_ports.return_value = 'fake_ports_callback'
    return fake_driver


def fake_worker_context():
    """Patches client API libs in the worker context.
    Caller should addCleanup(mock.patch.stopall).
    """
    fake_neutron_obj = mock.patch.object(
        neutron, 'Neutron', autospec=True).start()
    mock.patch.object(
        neutron, 'Neutron', return_value=fake_neutron_obj).start()
    fake_nova_obj = mock.patch.object(
        nova, 'Nova', autospec=True).start()
    mock.patch.object(
        nova, 'Nova', return_value=fake_nova_obj).start()
    return worker.WorkerContext()
