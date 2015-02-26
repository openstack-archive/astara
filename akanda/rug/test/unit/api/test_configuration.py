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


import mock
import netaddr
from oslo.config import cfg
import unittest2 as unittest

from akanda.rug.api import configuration as conf_mod
from akanda.rug.api.neutron import Subnet


class FakeModel(object):
    def __init__(self, id_, **kwargs):
        self.id = id_
        self.__dict__.update(kwargs)

fake_ext_port = FakeModel(
    '1',
    mac_address='aa:bb:cc:dd:ee:ff',
    network_id='ext-net',
    fixed_ips=[FakeModel('', ip_address='9.9.9.9', subnet_id='s2')],
    first_v4='9.9.9.9',
    device_id='e-e-e-e')


fake_mgt_port = FakeModel(
    '2',
    mac_address='aa:bb:cc:cc:bb:aa',
    network_id='mgt-net',
    device_id='m-m-m-m')

fake_int_port = FakeModel(
    '3',
    mac_address='aa:aa:aa:aa:aa:aa',
    network_id='int-net',
    fixed_ips=[FakeModel('', ip_address='192.168.1.1', subnet_id='s1')],
    device_id='i-i-i-i')

fake_vm_port = FakeModel(
    '4',
    mac_address='aa:aa:aa:aa:aa:bb',
    network_id='int-net',
    fixed_ips=[FakeModel('', ip_address='192.168.1.2', subnet_id='s1')],
    first_v4='192.168.1.2',
    device_id='v-v-v-v')

fake_subnet = FakeModel(
    's1',
    cidr=netaddr.IPNetwork('192.168.1.0/24'),
    gateway_ip='192.168.1.1',
    enable_dhcp=True,
    dns_nameservers=['8.8.8.8'],
    ipv6_ra_mode=None,
    host_routes={})

fake_subnet_with_slaac = Subnet(
    id_='fake_id',
    name='s1',
    tenant_id='fake_tenant_id',
    network_id='fake_network_id',
    ip_version=6,
    cidr='fdee:9f85:83be::/48',
    gateway_ip='fdee:9f85:83be::1',
    enable_dhcp=True,
    dns_nameservers=['8.8.8.8'],
    ipv6_ra_mode='slaac',
    host_routes={})

fake_router = FakeModel(
    'router_id',
    tenant_id='tenant_id',
    name='router_name',
    external_port=fake_ext_port,
    management_port=fake_mgt_port,
    internal_ports=[fake_int_port])


class TestAkandaClient(unittest.TestCase):
    def setUp(self):
        cfg.CONF.set_override('provider_rules_path', '/the/path')

    def tearDown(self):
        cfg.CONF.reset()

    def test_build_config(self):
        methods = {
            'load_provider_rules': mock.DEFAULT,
            'generate_network_config': mock.DEFAULT,
            'generate_floating_config': mock.DEFAULT,
            'get_default_v4_gateway': mock.DEFAULT,
        }

        mock_client = mock.Mock()
        ifaces = []
        provider_rules = {'labels': {'ext': ['192.168.1.1']}}
        network_config = [
            {'interface': 1,
             'network_id': 2,
             'v4_conf_service': 'static',
             'v6_conf_service': 'static',
             'network_type': 'external',
             'subnets': [
                 {'cidr': '192.168.1.0/24',
                  'dhcp_enabled': True,
                  'dns_nameservers': [],
                  'host_routes': [],
                  'gateway_ip': '192.168.1.1',
                  },
                 {'cidr': '10.0.0.0/24',
                  'dhcp_enabled': True,
                  'dns_nameservers': [],
                  'host_routes': [],
                  'gateway_ip': '10.0.0.1',
                  },
                 ],
             'allocations': []}
        ]

        with mock.patch.multiple(conf_mod, **methods) as mocks:
            mocks['load_provider_rules'].return_value = provider_rules
            mocks['generate_network_config'].return_value = network_config
            mocks['generate_floating_config'].return_value = 'floating_config'
            mocks['get_default_v4_gateway'].return_value = 'default_gw'

            config = conf_mod.build_config(mock_client, fake_router, ifaces)

            expected = {
                'default_v4_gateway': 'default_gw',
                'networks': network_config,
                'labels': {'ext': ['192.168.1.1']},
                'floating_ips': 'floating_config',
                'asn': 64512,
                'neighbor_asn': 64512,
                'tenant_id': 'tenant_id',
                'hostname': 'router_name'
            }

            self.assertEqual(config, expected)

            mocks['load_provider_rules'].assert_called_once_with('/the/path')
            mocks['generate_network_config'].assert_called_once_with(
                mock_client, fake_router, ifaces)

    def test_load_provider_rules(self):
        rules_dict = {'labels': {}, 'preanchors': [], 'postanchors': []}
        with mock.patch('akanda.rug.openstack.common.jsonutils.load') as load:
            load.return_value = rules_dict
            with mock.patch('__builtin__.open') as mock_open:
                r = conf_mod.load_provider_rules('/the/path')

                mock_open.assert_called_once_with('/the/path')
                load.assert_called_once_with(mock_open.return_value)
                self.assertEqual(r, rules_dict)

    def test_generate_network_config(self):
        methods = {
            '_network_config': mock.DEFAULT,
            '_management_network_config': mock.DEFAULT,
        }

        mock_client = mock.Mock()

        ifaces = [
            {'ifname': 'ge0', 'lladdr': fake_mgt_port.mac_address},
            {'ifname': 'ge1', 'lladdr': fake_ext_port.mac_address},
            {'ifname': 'ge2', 'lladdr': fake_int_port.mac_address}
        ]

        with mock.patch.multiple(conf_mod, **methods) as mocks:
            mocks['_network_config'].return_value = 'configured_network'
            mocks['_management_network_config'].return_value = 'mgt_net'

            result = conf_mod.generate_network_config(
                mock_client, fake_router, ifaces)

            expected = [
                'configured_network',
                'mgt_net',
                'configured_network'
            ]

            self.assertEqual(result, expected)

            mocks['_network_config'].assert_has_calls([
                mock.call(
                    mock_client,
                    fake_router.external_port,
                    'ge1',
                    'external'),
                mock.call(
                    mock_client,
                    fake_int_port,
                    'ge2',
                    'internal',
                    mock.ANY)])

            mocks['_management_network_config'].assert_called_once_with(
                fake_router.management_port, 'ge0', ifaces)

    def test_managment_network_config(self):
        with mock.patch.object(conf_mod, '_make_network_config_dict') as nc:
            interface = {
                'ifname': 'ge0',
            }

            ifaces = [interface]

            conf_mod._management_network_config(fake_mgt_port, 'ge0', ifaces)
            nc.assert_called_once_with(interface, 'management', 'mgt-net')

    def test_network_config(self):
        mock_client = mock.Mock()
        mock_client.get_network_subnets.return_value = [fake_subnet]
        subnets_dict = {fake_subnet.id: fake_subnet}

        with mock.patch.object(conf_mod, '_make_network_config_dict') as nc:
            with mock.patch.object(conf_mod, '_interface_config') as ic:
                mock_interface = mock.Mock()
                ic.return_value = mock_interface

                conf_mod._network_config(
                    mock_client,
                    fake_int_port,
                    'ge1',
                    'internal',
                    [])

                ic.assert_called_once_with('ge1', fake_int_port, subnets_dict)
                nc.assert_called_once_with(
                    mock_interface,
                    'internal',
                    'int-net',
                    subnets_dict=subnets_dict,
                    network_ports=[])

    def test_make_network_config(self):
        interface = {'ifname': 'ge2'}

        result = conf_mod._make_network_config_dict(
            interface,
            'internal',
            fake_int_port.network_id,
            'dhcp',
            'ra',
            subnets_dict={fake_subnet.id: fake_subnet},
            network_ports=[fake_vm_port])

        expected = {
            'interface': interface,
            'network_id': fake_int_port.network_id,
            'v4_conf_service': 'dhcp',
            'v6_conf_service': 'ra',
            'network_type': 'internal',
            'subnets': [{'cidr': '192.168.1.0/24',
                         'dhcp_enabled': True,
                         'dns_nameservers': ['8.8.8.8'],
                         'gateway_ip': '192.168.1.1',
                         'host_routes': {}}],
            'allocations': [
                {
                    'mac_address': 'aa:aa:aa:aa:aa:bb',
                    'ip_addresses': {'192.168.1.2': True},
                    'hostname': '192-168-1-2.local',
                    'device_id': 'v-v-v-v'
                }
            ]
        }

        self.assertEqual(result, expected)

    def test_interface_config(self):
        expected = {'addresses': ['192.168.1.1/24'], 'ifname': 'ge1'}
        subnets_dict = {fake_subnet.id: fake_subnet}

        self.assertEqual(
            expected,
            conf_mod._interface_config('ge1', fake_int_port, subnets_dict))

    def test_subnet_config(self):
        expected = {
            'cidr': '192.168.1.0/24',
            'dhcp_enabled': True,
            'dns_nameservers': ['8.8.8.8'],
            'gateway_ip': '192.168.1.1',
            'host_routes': {}
        }
        self.assertEqual(conf_mod._subnet_config(fake_subnet), expected)

    def test_subnet_config_with_slaac_enabled(self):
        expected = {
            'cidr': 'fdee:9f85:83be::/48',
            'dhcp_enabled': False,
            'dns_nameservers': ['8.8.8.8'],
            'gateway_ip': 'fdee:9f85:83be::1',
            'host_routes': {}
        }
        self.assertEqual(
            conf_mod._subnet_config(fake_subnet_with_slaac), expected)

    def test_subnet_config_no_gateway(self):
        expected = {
            'cidr': '192.168.1.0/24',
            'dhcp_enabled': True,
            'dns_nameservers': ['8.8.8.8'],
            'gateway_ip': '',
            'host_routes': {}
        }
        sn = FakeModel(
            's1',
            cidr=netaddr.IPNetwork('192.168.1.0/24'),
            gateway_ip='',
            enable_dhcp=True,
            dns_nameservers=['8.8.8.8'],
            ipv6_ra_mode='',
            host_routes={})
        self.assertEqual(conf_mod._subnet_config(sn), expected)

    def test_subnet_config_gateway_none(self):
        expected = {
            'cidr': '192.168.1.0/24',
            'dhcp_enabled': True,
            'dns_nameservers': ['8.8.8.8'],
            'gateway_ip': '',
            'host_routes': {}
        }
        sn = FakeModel(
            's1',
            cidr=netaddr.IPNetwork('192.168.1.0/24'),
            gateway_ip=None,
            enable_dhcp=True,
            dns_nameservers=['8.8.8.8'],
            ipv6_ra_mode='',
            host_routes={})
        self.assertEqual(conf_mod._subnet_config(sn), expected)

    def test_allocation_config(self):
        subnets_dict = {fake_subnet.id: fake_subnet}
        expected = [
            {'mac_address': 'aa:aa:aa:aa:aa:bb',
             'ip_addresses': {'192.168.1.2': True},
             'hostname': '192-168-1-2.local',
             'device_id': 'v-v-v-v'}
        ]

        self.assertEqual(
            conf_mod._allocation_config([fake_vm_port], subnets_dict),
            expected
        )

    def test_generate_floating_config(self):
        fip = FakeModel(
            'id',
            floating_ip=netaddr.IPAddress('9.9.9.9'),
            fixed_ip=netaddr.IPAddress('192.168.1.1')
        )

        rtr = FakeModel('rtr_id', floating_ips=[fip])

        result = conf_mod.generate_floating_config(rtr)
        expected = [{'floating_ip': '9.9.9.9', 'fixed_ip': '192.168.1.1'}]

        self.assertEqual(result, expected)


class TestAkandaClientGateway(unittest.TestCase):

    def setUp(self):
        cfg.CONF.set_override('provider_rules_path', '/the/path')
        # Sample data taken from a real devstack-created system, with
        # the external MAC address modified to match the fake port in
        # use for the mocked router.
        self.networks = [
            {'subnets': [
                {'host_routes': [],
                 'cidr': '172.16.77.0/24',
                 'gateway_ip': '172.16.77.1',
                 'dns_nameservers': [],
                 'dhcp_enabled': True,
                 'network_type': 'external'},
                {'host_routes': [],
                 'cidr': 'fdee:9f85:83be::/48',
                 'gateway_ip': 'fdee:9f85:83be::1',
                 'dns_nameservers': [],
                 'dhcp_enabled': True}],
             'v6_conf_service': 'static',
             'network_id': u'1e109e80-4a6a-483e-9dd4-2ff31adf25f5',
             'allocations': [],
             'interface': {'ifname': u'ge1',
                           'addresses': [
                               '172.16.77.2/24',
                               'fdee:9f85:83be:0:f816:3eff:fee5:1742/48',
                           ]},
             'v4_conf_service': 'static',
             'network_type': 'external'},
            {'subnets': [],
             'v6_conf_service': 'static',
             'network_id': u'698ef1d1-1089-48ab-80b0-f994a962891c',
             'allocations': [],
             'interface': {
                 u'addresses': [
                     u'fe80::f816:3eff:fe4d:bf12/64',
                     u'fdca:3ba5:a17a:acda:f816:3eff:fe4d:bf12/64',
                 ],
                 u'media': u'Ethernet autoselect',
                 u'lladdr': u'fa:16:3e:4d:bf:12',
                 u'state': u'up',
                 u'groups': [],
                 u'ifname': u'ge0',
                 u'mtu': 1500,
                 u'description': u''},
             'v4_conf_service': 'static',
             'network_type': 'management'},
            {'subnets': [
                {'host_routes': [],
                 'cidr': 'fdd6:a1fa:cfa8:6c94::/64',
                 'gateway_ip': 'fdd6:a1fa:cfa8:6c94::1',
                 'dns_nameservers': [],
                 'dhcp_enabled': False},
                {'host_routes': [],
                 'cidr': '192.168.0.0/24',
                 'gateway_ip': '192.168.0.1',
                 'dns_nameservers': [],
                 'dhcp_enabled': True}],
             'v6_conf_service': 'static',
             'network_id': u'a1ea2256-5e57-4e9e-8b7a-8bf17eb76b73',
             'allocations': [
                 {'mac_address': u'fa:16:3e:1b:93:76',
                  'ip_addresses': {
                      'fdd6:a1fa:cfa8:6c94::1': False,
                      '192.168.0.1': True},
                  'hostname': '192-168-0-1.local',
                  'device_id': u'c72a34fb-fb56-4ee7-b9b2-6467eb1c45d6'}],
             'interface': {'ifname': u'ge2',
                           'addresses': ['192.168.0.1/24',
                                         'fdd6:a1fa:cfa8:6c94::1/64']},
             'v4_conf_service': 'static',
             'network_type': 'internal'}]

    def tearDown(self):
        cfg.CONF.reset()

    def test_with_interfaces(self):
        mock_client = mock.Mock()
        result = conf_mod.get_default_v4_gateway(
            mock_client,
            fake_router,
            self.networks,
        )
        self.assertEqual(result, '172.16.77.1')

    def test_without_ipv4_on_external_port(self):
        # Only set a V6 address
        self.networks[0]['interface']['addresses'] = [
            'fdee:9f85:83be:0:f816:3eff:fee5:1742/48',
        ]
        mock_client = mock.Mock()
        result = conf_mod.get_default_v4_gateway(
            mock_client,
            fake_router,
            self.networks,
        )
        self.assertEqual(result, '')

    def test_extra_ipv4_on_external_port(self):
        self.networks[0]['interface']['addresses'] = [
            u'fe80::f816:3eff:fe4d:bf12/64',
            u'fdca:3ba5:a17a:acda:f816:3eff:fe4d:bf12/64',
            u'192.168.1.1',
            u'172.16.77.2',
        ]
        mock_client = mock.Mock()
        result = conf_mod.get_default_v4_gateway(
            mock_client,
            fake_router,
            self.networks,
        )
        self.assertEqual(result, '172.16.77.1')
