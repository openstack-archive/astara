import mock
import netaddr
import unittest2 as unittest

from akanda.rug.api import quantum


class TestQuantumModels(unittest.TestCase):
    def test_router(self):
        r = quantum.Router(
            '1', 'tenant_id', 'name', True, 'ext', ['int'], 'mgt')
        self.assertEqual(r.id, '1')
        self.assertEqual(r.tenant_id, 'tenant_id')
        self.assertEqual(r.name, 'name')
        self.assertTrue(r.admin_state_up)
        self.assertEqual(r.external_port, 'ext')
        self.assertEqual(r.management_port, 'mgt')
        self.assertEqual(r.internal_ports, ['int'])


    def test_router_from_dict(self):
        d = {
            'id': '1',
            'tenant_id': 'tenant_id',
            'name': 'name',
            'admin_state_up': True,
            'external_port': 'ext',
            'ports' : []
        }

        r = quantum.Router.from_dict(d)

        self.assertEqual(r.id, '1')
        self.assertEqual(r.tenant_id, 'tenant_id')
        self.assertEqual(r.name, 'name')
        self.assertTrue(r.admin_state_up)
        self.assertEqual(r.external_port, 'ext')

    def test_router_eq(self):
        r1 = quantum.Router(
            '1', 'tenant_id', 'name', True, 'ext', ['int'], 'mgt')
        r2 = quantum.Router(
            '1', 'tenant_id', 'name', True, 'ext', ['int'], 'mgt')

        self.assertEqual(r1, r2)

    def test_router_ne(self):
        r1 = quantum.Router(
            '1', 'tenant_id', 'name', True, 'ext', ['int'], 'mgt')
        r2 = quantum.Router(
            '2', 'tenant_id', 'name', True, 'ext', ['int'], 'mgt')

        self.assertNotEqual(r1, r2)


    def test_subnet_model(self):
        d = {
            'id': '1',
            'tenant_id': 'tenant_id',
            'name': 'name',
            'network_id': 'network_id',
            'ip_version': 6,
            'cidr': 'fe80::/64',
            'gateway_ip': 'fe80::1',
            'enable_dhcp': True,
            'dns_nameservers': ['8.8.8.8', '8.8.4.4'],
            'host_routes': []
        }

        s = quantum.Subnet.from_dict(d)

        self.assertEqual(s.id, '1')
        self.assertEqual(s.tenant_id, 'tenant_id')
        self.assertEqual(s.name, 'name')
        self.assertEqual(s.network_id, 'network_id')
        self.assertEqual(s.ip_version, 6)
        self.assertEqual(s.cidr, netaddr.IPNetwork('fe80::/64'))
        self.assertEqual(s.gateway_ip, netaddr.IPAddress('fe80::1'))
        self.assertTrue(s.enable_dhcp, True)
        self.assertEqual(s.dns_nameservers, ['8.8.8.8', '8.8.4.4'])
        self.assertEqual(s.host_routes, [])

    def test_port_model(self):
        d = {
            'id': '1',
            'device_id': 'device_id',
            'fixed_ips': [{'ip_address': '192.168.1.1', 'subnet_id': 'sub1'}],
            'mac_address': 'aa:bb:cc:dd:ee:ff',
            'network_id': 'net_id',
            'device_owner': 'test'
        }

        p = quantum.Port.from_dict(d)

        self.assertEqual(p.id, '1')
        self.assertEqual(p.device_id, 'device_id')
        self.assertEqual(p.mac_address, 'aa:bb:cc:dd:ee:ff')
        self.assertEqual(p.device_owner, 'test')
        self.assertEqual(len(p.fixed_ips), 1)


    def test_fixed_ip_model(self):
        d = {
            'subnet_id': 'sub1',
            'ip_address': '192.168.1.1'
        }

        fip = quantum.FixedIp.from_dict(d)

        self.assertEqual(fip.subnet_id, 'sub1')
        self.assertEqual(fip.ip_address, netaddr.IPAddress('192.168.1.1'))

    def test_addressgroup_model(self):
        d = {
            'id': '1',
            'name': 'group1',
            'entries': [{'cidr': '192.168.1.1/24'}]
        }

        g = quantum.AddressGroup.from_dict(d)

        self.assertEqual(g.id, '1')
        self.assertEqual(g.name, 'group1')
        self.assertEqual(g.entries, [netaddr.IPNetwork('192.168.1.1/24')])


    def test_filterrule_model(self):
        d = {
            'id': '1',
            'action': 'pass',
            'protocol': 'tcp',
            'source': {'id': '1',
                       'name': 'group',
                       'entries': [{'cidr': '192.168.1.1/24'}]},
            'source_port': None,
            'destination': None,
            'destination_port': 80
        }

        r = quantum.FilterRule.from_dict(d)

        self.assertEqual(r.id, '1')
        self.assertEqual(r.action, 'pass')
        self.assertEqual(r.protocol, 'tcp')
        self.assertEqual(r.source.name, 'group')
        self.assertIsNone(r.source_port)
        self.assertIsNone(r.destination)
        self.assertEqual(r.destination_port, 80)

    def test_portforward_model(self):
        p = {
            'id': '1',
            'device_id': 'device_id',
            'fixed_ips': [{'ip_address': '192.168.1.1', 'subnet_id': 'sub1'}],
            'mac_address': 'aa:bb:cc:dd:ee:ff',
            'network_id': 'net_id',
            'device_owner': 'test'
        }

        d = {
            'id': '1',
            'name': 'name',
            'protocol': 'tcp',
            'public_port': 8022,
            'private_port': 22,
            'port': p
        }

        fw = quantum.PortForward.from_dict(d)

        self.assertEqual(fw.id, '1')
        self.assertEqual(fw.name, 'name')
        self.assertEqual(fw.protocol, 'tcp')
        self.assertEqual(fw.public_port, 8022)
        self.assertEqual(fw.private_port, 22)
        self.assertEqual(fw.port.device_id, 'device_id')

class FakeConf:
    admin_user='admin'
    admin_password='password'
    admin_tenant_name='admin'
    auth_url='http://127.0.0.1/'
    auth_strategy='keystone'
    auth_region='RegionOne'


class TestAkandaClientWrapper(unittest.TestCase):
    pass
