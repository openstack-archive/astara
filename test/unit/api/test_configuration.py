import mock
import netaddr
from oslo.config import cfg
import unittest2 as unittest

from akanda.rug.api import configuration as conf_mod


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
    host_routes={})

fake_router = FakeModel(
    'router_id',
    tenant_id='tenant_id',
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
            'generate_address_book_config': mock.DEFAULT,
            'generate_anchor_config': mock.DEFAULT,
            'generate_floating_config': mock.DEFAULT
        }

        mock_client = mock.Mock()
        ifaces = []
        provider_rules = {'labels': {'ext': ['192.168.1.1']}}

        with mock.patch.multiple(conf_mod, **methods) as mocks:
            mocks['load_provider_rules'].return_value = provider_rules
            mocks['generate_network_config'].return_value = 'network_config'
            mocks['generate_address_book_config'].return_value = 'ab_config'
            mocks['generate_anchor_config'].return_value = 'anchor_config'
            mocks['generate_floating_config'].return_value = 'floating_config'

            config = conf_mod.build_config(mock_client, fake_router, ifaces)

            expected = {
                'networks': 'network_config',
                'address_book': 'ab_config',
                'anchors': 'anchor_config',
                'labels': {'ext': ['192.168.1.1']},
                'floating_ips': 'floating_config'
            }

            self.assertEqual(config, expected)

            mocks['load_provider_rules'].assert_called_once_with('/the/path')
            mocks['generate_network_config'].assert_called_once_with(
                mock_client, fake_router, ifaces)
            mocks['generate_address_book_config'].assert_called_once_with(
                mock_client, fake_router)
            mocks['generate_anchor_config'].assert_called_once_with(
                mock_client, provider_rules, fake_router)

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

    def test_generate_address_book_config(self):
        fake_address_group = FakeModel(
            'g1',
            name='local_net',
            entries=[netaddr.IPNetwork('10.0.0.0/8')])

        mock_client = mock.Mock()
        mock_client.get_addressgroups.return_value = [fake_address_group]

        result = conf_mod.generate_address_book_config(mock_client,
                                                       fake_router)

        expected = {'local_net': ['10.0.0.0/8']}
        self.assertEqual(result, expected)

    def test_generate_anchor_config(self):
        mock_client = mock.Mock()
        provider_rules = {
            'preanchors': ['pre'],
            'postanchors': ['post']
        }

        methods = {
            'generate_tenant_port_forward_anchor': mock.DEFAULT,
            'generate_tenant_filter_rule_anchor': mock.DEFAULT
        }

        with mock.patch.multiple(conf_mod, **methods) as mocks:
            mocks['generate_tenant_port_forward_anchor'].return_value = 'fwd'
            mocks['generate_tenant_filter_rule_anchor'].return_value = 'filter'

            result = conf_mod.generate_anchor_config(
                mock_client, provider_rules, fake_router)

        expected = ['pre', 'fwd', 'filter', 'post']
        self.assertEqual(result, expected)

    def test_generate_port_forward_anchor(self):
        port_forward = FakeModel(
            'pf1',
            protocol='tcp',
            public_port=8080,
            private_port=80,
            port=fake_vm_port)

        mock_client = mock.Mock()
        mock_client.get_portforwards.return_value = [port_forward]

        result = conf_mod.generate_tenant_port_forward_anchor(
            mock_client, fake_router)

        expected = {
            'name': 'tenant_v4_portforwards',
            'rules': [
                {
                    'action': 'pass',
                    'direction': 'in',
                    'family': 'inet',
                    'protocol': 'tcp',
                    'redirect': '192.168.1.2',
                    'redirect_port': 80,
                    'destination': '9.9.9.9/32',
                    'destination_port': 8080
                }
            ]
        }

        self.assertEqual(result, expected)

    def test_generate_filter_rule_anchor(self):
        dest_rule = FakeModel(
            'fr1',
            action='pass',
            protocol='tcp',
            source=None,
            source_port=None,
            destination=FakeModel('d1', name='webservers'),
            destination_port=80)

        source_rule = FakeModel(
            'fr1',
            action='pass',
            protocol='tcp',
            source=FakeModel('s1', name='home'),
            source_port=None,
            destination=None,
            destination_port=22)

        mock_client = mock.Mock()
        mock_client.get_filterrules.return_value = [dest_rule, source_rule]

        result = conf_mod.generate_tenant_filter_rule_anchor(
            mock_client, fake_router)

        expected = {
            'name': 'tenant_filterrules',
            'rules': [{'action': 'pass',
                       'destination': 'webservers',
                       'destination_port': 80,
                       'protocol': 'tcp',
                       'source': None,
                       'source_port': None},
                      {'action': 'pass',
                       'destination': None,
                       'destination_port': 22,
                       'protocol': 'tcp',
                       'source': 'home',
                       'source_port': None}
                      ]
        }

        self.assertEqual(result, expected)

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
