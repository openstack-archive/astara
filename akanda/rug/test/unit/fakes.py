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


def fake_loadbalancer():
    lb_dict = {
        'name': u'balancer1',
        'status': u'ACTIVE',
        'tenant_id': u'd22b149cee9b4eac8349c517eda00b89',
        'vip_address': u'192.168.0.132',
        'provisioning_status': 'ACTIVE',
        'admin_state_up': True,
        'id': u'66636dbe-86f3-48e3-843f-13b05f93dd84',
        'listeners': [
            {
                'id': u'e3491d85-4d41-4c2d-99ed-e2410343b163',
                'name': u'listener1',
                'protocol': u'HTTP',
                'protocol_port': 80,
                'tenant_id': u'd22b149cee9b4eac8349c517eda00b89',
                'admin_state_up': True,
                'default_pool': {
                    'name': u'pool1',
                    'protocol': u'HTTP',
                    'session_persistence': None,
                    'tenant_id': u'd22b149cee9b4eac8349c517eda00b89',
                    'admin_state_up': True,
                    'healthmonitor': None,
                    'id': u'ad75ea75-43e1-4f4a-9053-c66dd7235ff1',
                    'lb_algorithm': u'ROUND_ROBIN',
                    'members': [{
                        'address': '192.168.0.194',
                        'admin_state_up': True,
                        'id': u'ae70e3cd-41c9-4253-ade6-e555693d38bb',
                        'protocol_port': 80,
                        'subnet': None,
                        'tenant_id': u'd22b149cee9b4eac8349c517eda00b89',
                        'weight': 1}]}}],
        'vip_port': {
            'id': u'a3f398c5-a02a-4daa-8c9f-810b5a85ecdf',
            'mac_address': u'fa:16:3e:ff:32:7c',
            'name': u'loadbalancer-66636dbe-86f3-48e3-843f-13b05f93dd84',
            'network_id': u'b7fc9b39-401c-47cc-a07d-9f8cde75ccbf',
            'device_id': u'66636dbe-86f3-48e3-843f-13b05f93dd84',
            'device_owner': u'neutron:LOADBALANCERV2',
            'fixed_ips': [
                {'ip_address': '192.168.0.132',
                 'subnet_id': u'8c58b558-be54-45de-9873-169fe845bb80'},
                {'ip_address': 'fdd6:a1fa:cfa8:6af6:f816:3eff:feff:327c',
                 'subnet_id': u'89fe7a9d-be92-469c-9a1e-503a39462ed1'}]
            }
    }
    return neutron.LoadBalancer.from_dict(lb_dict)


def fake_port():
    port_dict = {
        u'admin_state_up': True,
        u'allowed_address_pairs': [],
        u'binding:host_id': u'trusty',
        u'binding:profile': {},
        u'binding:vif_details': {
            u'ovs_hybrid_plug': True, u'port_filter': True
        },
        u'binding:vif_type': u'ovs',
        u'binding:vnic_type': u'normal',
        u'device_id': u'fake_device_id',
        u'device_owner': u'network:astara',
        u'dns_assignment': [{
            u'fqdn': u'foo.openstacklocal.',
            u'hostname': u'host-fdca-3ba5-a17a-acda-f816-3eff-fe2b-ced0',
            u'ip_address': u'fdca:3ba5:a17a:acda:f816:3eff:fe2b:ced0'
        }],
        u'dns_name': u'',
        u'extra_dhcp_opts': [],
        u'fixed_ips': [{
            u'ip_address': u'fdca:3ba5:a17a:acda:f816:3eff:fe2b:ced0',
            u'subnet_id': 'fake_subnet_id',
        }],
        u'id': u'fake_port_id',
        u'mac_address': u'fa:16:3e:2b:ce:d0',
        u'name': u'ASTARA:RUG:SERVICE',
        u'network_id': u'fake_network_id',
        u'port_security_enabled': False,
        u'security_groups': [],
        u'status': u'ACTIVE',
        u'tenant_id': u'fake_tenant_id'
    }
    return neutron.Port.from_dict(port_dict)


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
    fake_driver.delete_ports.return_value = 'fake_delete_ports_callback'
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
