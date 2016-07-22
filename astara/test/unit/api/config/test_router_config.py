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
from oslo_config import cfg
import unittest2 as unittest
from six.moves import builtins as __builtins__

from astara.api.config import router as conf_mod

from astara.test.unit.api.config import config_fakes as fakes


class TestAstaraClient(unittest.TestCase):
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
        fake_orchestrator = {
            'host': 'foohost',
            'adddress': '10.0.0.1',
            'metadata_port': 80,
        }

        mock_client = mock.Mock()
        mock_context = mock.Mock(
            neutron=mock_client,
            config=fake_orchestrator,
        )
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
                  }, ],
             'allocations': []}
        ]

        with mock.patch.multiple(conf_mod, **methods) as mocks:
            mocks['load_provider_rules'].return_value = provider_rules
            mocks['generate_network_config'].return_value = network_config
            mocks['generate_floating_config'].return_value = 'floating_config'
            mocks['get_default_v4_gateway'].return_value = 'default_gw'

            config = conf_mod.build_config(mock_context, fakes.fake_router,
                                           fakes.fake_mgt_port, ifaces)

            expected = {
                'default_v4_gateway': 'default_gw',
                'networks': network_config,
                'labels': {'ext': ['192.168.1.1']},
                'floating_ips': 'floating_config',
                'asn': 64512,
                'neighbor_asn': 64512,
                'tenant_id': 'tenant_id',
                'ha_resource': False,
                'hostname': 'ak-tenant_id',
                'orchestrator': {
                    'host': 'foohost',
                    'adddress': '10.0.0.1',
                    'metadata_port': 80,
                },
                'vpn': {}
            }

            self.assertEqual(expected, config)

            mocks['load_provider_rules'].assert_called_once_with('/the/path')
            mocks['generate_network_config'].assert_called_once_with(
                mock_client, fakes.fake_router, fakes.fake_mgt_port, ifaces)

    def test_load_provider_rules(self):
        rules_dict = {'labels': {}, 'preanchors': [], 'postanchors': []}
        with mock.patch('oslo_serialization.jsonutils.load') as load:
            load.return_value = rules_dict
            with mock.patch('six.moves.builtins.open') as mock_open:
                r = conf_mod.load_provider_rules('/the/path')

                mock_open.assert_called_once_with('/the/path')
                load.assert_called_once_with(mock_open.return_value)
                self.assertEqual(rules_dict, r)

    @mock.patch.object(__builtins__, 'open', autospec=True)
    def test_load_provider_rules_not_found(self, mock_open):
        mock_open.side_effect = IOError()
        res = conf_mod.load_provider_rules('/tmp/path')
        self.assertEqual({}, res)

    @mock.patch('astara.api.config.common.network_config')
    def test_generate_network_config(self, mock_net_conf):
        mock_client = mock.Mock()

        iface_map = {
            fakes.fake_mgt_port.network_id: 'ge0',
            fakes.fake_ext_port.network_id: 'ge1',
            fakes.fake_int_port.network_id: 'ge2'
        }

        mock_net_conf.return_value = 'configured_network'

        result = conf_mod.generate_network_config(
            mock_client, fakes.fake_router, fakes.fake_mgt_port, iface_map)

        expected = [
            'configured_network',
            'configured_network',
            'configured_network'
        ]

        self.assertEqual(expected, result)

        expected_calls = [
            mock.call(
                mock_client, fakes.fake_router.management_port,
                'ge0', 'management'),
            mock.call(
                mock_client, fakes.fake_router.external_port,
                'ge1', 'external'),
            mock.call(
                mock_client, fakes.fake_int_port,
                'ge2', 'internal', mock.ANY)]
        for c in expected_calls:
            self.assertIn(c, mock_net_conf.call_args_list)
        mock_net_conf.assert_has_calls(expected_calls)

    def test_generate_floating_config(self):
        fip = fakes.FakeModel(
            'id',
            floating_ip=netaddr.IPAddress('9.9.9.9'),
            fixed_ip=netaddr.IPAddress('192.168.1.1')
        )

        rtr = fakes.FakeModel('rtr_id', floating_ips=[fip])

        result = conf_mod.generate_floating_config(rtr)
        expected = [{'floating_ip': '9.9.9.9', 'fixed_ip': '192.168.1.1'}]

        self.assertEqual(expected, result)


class TestAstaraClientGateway(unittest.TestCase):

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
            fakes.fake_router,
            self.networks,
        )
        self.assertEqual('172.16.77.1', result)

    def test_without_ipv4_on_external_port(self):
        # Only set a V6 address
        self.networks[0]['interface']['addresses'] = [
            'fdee:9f85:83be:0:f816:3eff:fee5:1742/48',
        ]
        mock_client = mock.Mock()
        result = conf_mod.get_default_v4_gateway(
            mock_client,
            fakes.fake_router,
            self.networks,
        )
        self.assertEqual('', result)

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
            fakes.fake_router,
            self.networks,
        )
        self.assertEqual('172.16.77.1', result)
