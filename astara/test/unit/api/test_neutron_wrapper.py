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


import copy

import mock
import netaddr

from oslo_config import cfg

from astara.test.unit import base, fakes
from astara.api import neutron


class TestuNeutronModels(base.RugTestBase):
    def test_router(self):
        r = neutron.Router(
            '1', 'tenant_id', 'name', True, 'ACTIVE', 'ext', ['int'], ['fip'])
        self.assertEqual(r.id, '1')
        self.assertEqual(r.tenant_id, 'tenant_id')
        self.assertEqual(r.name, 'name')
        self.assertTrue(r.admin_state_up)
        self.assertEqual(r.status, 'ACTIVE')
        self.assertEqual(r.external_port, 'ext')
        self.assertEqual(r.floating_ips, ['fip'])
        self.assertEqual(r.internal_ports, ['int'])
        self.assertEqual(set(['ext', 'int']), set(r.ports))

    def test_router_from_dict(self):
        p = {
            'id': 'ext',
            'device_id': 'device_id',
            'fixed_ips': [],
            'mac_address': 'aa:bb:cc:dd:ee:ff',
            'network_id': 'net_id',
            'device_owner': 'network:router_gateway'
        }

        fip = {
            'id': 'fip',
            'floating_ip_address': '9.9.9.9',
            'fixed_ip_address': '192.168.1.1'
        }

        d = {
            'id': '1',
            'tenant_id': 'tenant_id',
            'name': 'name',
            'admin_state_up': True,
            'status': 'ACTIVE',
            'ports': [p],
            '_floatingips': [fip]
        }

        r = neutron.Router.from_dict(d)

        self.assertEqual(r.id, '1')
        self.assertEqual(r.tenant_id, 'tenant_id')
        self.assertEqual(r.name, 'name')
        self.assertTrue(r.admin_state_up)
        self.assertTrue(r.floating_ips)  # just make sure this exists

    def test_router_eq(self):
        r1 = neutron.Router(
            '1', 'tenant_id', 'name', True, 'ext', ['int'], 'mgt')
        r2 = neutron.Router(
            '1', 'tenant_id', 'name', True, 'ext', ['int'], 'mgt')

        self.assertEqual(r1, r2)

    def test_router_ne(self):
        r1 = neutron.Router(
            '1', 'tenant_id', 'name', True, 'ext', ['int'], 'mgt')
        r2 = neutron.Router(
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
            'ipv6_ra_mode': 'slaac',
            'host_routes': []
        }

        s = neutron.Subnet.from_dict(d)

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

    def test_subnet_gateway_none(self):
        d = {
            'id': '1',
            'tenant_id': 'tenant_id',
            'name': 'name',
            'network_id': 'network_id',
            'ip_version': 6,
            'cidr': 'fe80::/64',
            'gateway_ip': None,
            'enable_dhcp': True,
            'dns_nameservers': ['8.8.8.8', '8.8.4.4'],
            'ipv6_ra_mode': 'slaac',
            'host_routes': []
        }
        s = neutron.Subnet.from_dict(d)
        self.assertEqual(s.cidr, netaddr.IPNetwork('fe80::/64'))
        self.assertIs(None, s.gateway_ip)

    def test_subnet_gateway_not_ip(self):
        d = {
            'id': '1',
            'tenant_id': 'tenant_id',
            'name': 'name',
            'network_id': 'network_id',
            'ip_version': 6,
            'cidr': 'fe80::/64',
            'gateway_ip': 'something-that-is-not-an-ip',
            'enable_dhcp': True,
            'dns_nameservers': ['8.8.8.8', '8.8.4.4'],
            'ipv6_ra_mode': 'slaac',
            'host_routes': []
        }
        s = neutron.Subnet.from_dict(d)
        self.assertEqual(s.cidr, netaddr.IPNetwork('fe80::/64'))
        self.assertIs(None, s.gateway_ip)

    def test_subnet_cidr_none(self):
        d = {
            'id': '1',
            'tenant_id': 'tenant_id',
            'name': 'name',
            'network_id': 'network_id',
            'ip_version': 6,
            'cidr': None,
            'gateway_ip': 'fe80::1',
            'enable_dhcp': True,
            'dns_nameservers': ['8.8.8.8', '8.8.4.4'],
            'ipv6_ra_mode': 'slaac',
            'host_routes': []
        }
        try:
            neutron.Subnet.from_dict(d)
        except ValueError as e:
            self.assertIn('Invalid CIDR', unicode(e))

    def test_subnet_cidr_not_valid(self):
        d = {
            'id': '1',
            'tenant_id': 'tenant_id',
            'name': 'name',
            'network_id': 'network_id',
            'ip_version': 6,
            'cidr': 'something-that-is-not-an-ip',
            'gateway_ip': 'fe80::1',
            'enable_dhcp': True,
            'dns_nameservers': ['8.8.8.8', '8.8.4.4'],
            'ipv6_ra_mode': 'slaac',
            'host_routes': []
        }
        try:
            neutron.Subnet.from_dict(d)
        except ValueError as e:
            self.assertIn('Invalid CIDR', unicode(e))

    def test_port_model(self):
        d = {
            'id': '1',
            'name': 'name',
            'device_id': 'device_id',
            'fixed_ips': [{'ip_address': '192.168.1.1', 'subnet_id': 'sub1'}],
            'mac_address': 'aa:bb:cc:dd:ee:ff',
            'network_id': 'net_id',
            'device_owner': 'test'
        }

        p = neutron.Port.from_dict(d)

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

        fip = neutron.FixedIp.from_dict(d)

        self.assertEqual(fip.subnet_id, 'sub1')
        self.assertEqual(fip.ip_address, netaddr.IPAddress('192.168.1.1'))

    def test_floating_ip_model(self):
        d = {
            'id': 'a-b-c-d',
            'floating_ip_address': '9.9.9.9',
            'fixed_ip_address': '192.168.1.1'
        }

        fip = neutron.FloatingIP.from_dict(d)

        self.assertEqual(fip.id, 'a-b-c-d')
        self.assertEqual(fip.floating_ip, netaddr.IPAddress('9.9.9.9'))
        self.assertEqual(fip.fixed_ip, netaddr.IPAddress('192.168.1.1'))


class FakeConf:
    admin_user = 'admin'
    admin_password = 'password'
    admin_tenant_name = 'admin'
    auth_url = 'http://127.0.0.1/'
    auth_strategy = 'keystone'
    auth_region = 'RegionOne'


class TestNeutronWrapper(base.RugTestBase):
    @mock.patch('astara.api.neutron.cfg')
    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    @mock.patch('astara.api.neutron.importutils')
    def test_purge_management_interface(self, import_utils, ak_wrapper, cfg):
        conf = mock.Mock()
        driver = mock.Mock()
        import_utils.import_object.return_value = driver

        neutron_wrapper = neutron.Neutron(conf)
        neutron_wrapper.purge_management_interface()
        self.assertEqual(driver.get_device_name.call_count, 1)
        self.assertEqual(driver.unplug.call_count, 1)

    def test_clear_device_id(self):
        neutron_wrapper = neutron.Neutron(mock.Mock())
        neutron_wrapper.api_client.update_port = mock.Mock()
        neutron_wrapper.clear_device_id(mock.Mock(id='PORT1'))
        neutron_wrapper.api_client.update_port.assert_called_once_with(
            'PORT1', {'port': {'device_id': ''}}
        )

    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    def test_neutron_router_status_update_error(self, client_wrapper):
        urs = client_wrapper.return_value.update_status
        urs.side_effect = RuntimeError('should be caught')
        conf = mock.Mock()
        neutron_wrapper = neutron.Neutron(conf)
        neutron_wrapper.update_router_status('router-id', 'new-status')

    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    def _test_create_vrrp_port_success_hlpr(self, ext_enabled, client_wrapper):
        conf = mock.Mock()
        conf.neutron_port_security_extension_enabled = ext_enabled

        expected_port_data = {
            'port': {
                'name': 'ASTARA:VRRP:obj_id',
                'admin_state_up': True,
                'network_id': 'the_net_id',
                'fixed_ips': [],
                'security_groups': []
            }
        }

        if ext_enabled:
            expected_port_data['port']['port_security_enabled'] = False

        neutron_wrapper = neutron.Neutron(conf)
        api_client = neutron_wrapper.api_client
        with mock.patch.object(api_client, 'create_port') as create_port:
            with mock.patch.object(neutron.Port, 'from_dict') as port_from_d:
                retval = neutron_wrapper.create_vrrp_port(
                    'obj_id',
                    'the_net_id'
                )

                self.assertIs(retval, port_from_d.return_value)
                port_from_d.assert_called_once_with(
                    create_port.return_value.get()
                )
                create_port.assert_called_once_with(
                    expected_port_data
                )

    def test_create_vrrp_port_success(self):
        self._test_create_vrrp_port_success_hlpr(True)

    def test_create_vrrp_port_success_port_security_disabled(self):
        self._test_create_vrrp_port_success_hlpr(False)

    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    def test_create_vrrp_port_error(self, client_wrapper):
        neutron_wrapper = neutron.Neutron(mock.Mock())
        api_client = neutron_wrapper.api_client
        with mock.patch.object(api_client, 'create_port') as create_port:
            create_port.return_value.get.return_value = None
            self.assertRaises(
                ValueError,
                neutron_wrapper.create_vrrp_port,
                'obj_id',
                'the_net_id'
            )

    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    def test_delete_vrrp_ports(self, client_wrapper):
        conf = mock.Mock()
        neutron_wrapper = neutron.Neutron(conf)
        neutron_wrapper.api_client.list_ports = mock.Mock(
            return_value={
                'ports': [{'id': 'fake_port_id'}]
            }
        )
        neutron_wrapper.api_client.delete_port = mock.Mock()
        neutron_wrapper.delete_vrrp_port(object_id='foo')
        neutron_wrapper.api_client.list_ports.assert_called_with(
            name='ASTARA:VRRP:foo'
        )
        neutron_wrapper.api_client.delete_port.assert_called_with(
            'fake_port_id')

    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    def test_delete_vrrp_ports_not_found(self, client_wrapper):
        conf = mock.Mock()
        neutron_wrapper = neutron.Neutron(conf)
        neutron_wrapper.api_client.list_ports = mock.Mock(
            return_value={'ports': []}
        )
        neutron_wrapper.api_client.delete_port = mock.Mock()
        neutron_wrapper.delete_vrrp_port(object_id='foo')
        neutron_wrapper.api_client.list_ports.assert_has_calls(
            [
                mock.call(name='ASTARA:VRRP:foo'),
                mock.call(name='AKANDA:VRRP:foo'),
            ]
        )
        self.assertFalse(neutron_wrapper.api_client.delete_port.called)


class TestExternalPort(base.RugTestBase):

    EXTERNAL_NET_ID = 'a0c63b93-2c42-4346-909e-39c690f53ba0'
    EXTERNAL_PORT_ID = '089ae859-10ec-453c-b264-6c452fc355e5'
    ROUTER = {
        u'status': u'ACTIVE',
        u'external_gateway_info': {
            u'network_id': EXTERNAL_NET_ID,
            u'enable_snat': True},
        u'name': u'ak-b81e555336da4bf48886e5b93ac6186d',
        u'admin_state_up': True,
        u'tenant_id': u'b81e555336da4bf48886e5b93ac6186d',
        u'ports': [
            # This is the external port:
            {u'status': u'ACTIVE',
             u'binding:host_id': u'devstack-develop',
             u'name': u'',
             u'allowed_address_pairs': [],
             u'admin_state_up': True,
             u'network_id': EXTERNAL_NET_ID,
             u'tenant_id': u'',
             u'extra_dhcp_opts': [],
             u'binding:vif_type': u'ovs',
             u'device_owner': u'network:router_gateway',
             u'binding:capabilities': {u'port_filter': True},
             u'mac_address': u'fa:16:3e:a1:a6:ac',
             u'fixed_ips': [
                 {u'subnet_id': u'ipv4snid',
                  u'ip_address': u'172.16.77.2'},
                 {u'subnet_id': u'ipv6snid',
                  u'ip_address': u'fdee:9f85:83be::0'}],
             u'id': EXTERNAL_PORT_ID,
             u'security_groups': [],
             u'device_id': u'7770b189-1223-4d85-9bf7-4d7bc2a28cd7'},
            # Some other nice ports you might like:
            {u'status': u'ACTIVE',
             u'binding:host_id': u'devstack-develop',
             u'name': u'',
             u'allowed_address_pairs': [],
             u'admin_state_up': True,
             u'network_id': u'adf190e0-b281-4453-bd87-4ae6fd96d5c1',
             u'tenant_id': u'a09298ceed154d26b4ea96977e1c7f17',
             u'extra_dhcp_opts': [],
             u'binding:vif_type': u'ovs',
             u'device_owner': u'network:router_management',
             u'binding:capabilities': {u'port_filter': True},
             u'mac_address': u'fa:16:3e:e5:dd:55',
             u'fixed_ips': [
                 {u'subnet_id': u'ipv6snid2',
                  u'ip_address': u'fdca:3ba5:a17a:acda::0'}],
             u'id': u'2f4e41b2-c923-48e5-ad19-59e4d02c26a4',
             u'security_groups': [],
             u'device_id': u'7770b189-1223-4d85-9bf7-4d7bc2a28cd7'},
            {u'status': u'ACTIVE',
             u'binding:host_id': u'devstack-develop',
             u'name': u'',
             u'allowed_address_pairs': [],
             u'admin_state_up': True,
             u'network_id': u'0c04f39c-f739-44dd-9e65-dca6ae20e35c',
             u'tenant_id': u'b81e555336da4bf48886e5b93ac6186d',
             u'extra_dhcp_opts': [],
             u'binding:vif_type': u'ovs',
             u'device_owner': u'network:router_interface',
             u'binding:capabilities': {u'port_filter': True},
             u'mac_address': u'fa:16:3e:e7:27:fc',
             u'fixed_ips': [{u'subnet_id': u'ipv4snid2',
                             u'ip_address': u'192.168.0.1'},
                            {u'subnet_id': u'ipv6snid3',
                             u'ip_address': u'fdd6:a1fa:cfa8:cd70::1'}],
             u'id': u'b24139b8-a3d0-46cf-bc53-f4b70bb33596',
             u'security_groups': [],
             u'device_id': u'7770b189-1223-4d85-9bf7-4d7bc2a28cd7'}],
        u'routes': [],
        u'id': u'5366e8ca-b3e4-408a-91d4-e207af48c755',
    }

    SUBNETS = [
        neutron.Subnet(u'ipv4snid', u'ipv4snid', None, None, 4,
                       '172.16.77.0/24', '172.16.77.1', False,
                       [], [], None),
        neutron.Subnet(u'ipv6snid', u'ipv4snid', None, None, 6,
                       'fdee:9f85:83be::/48', 'fdee:9f85:83be::1',
                       False, [], [], None),
    ]

    def setUp(self):
        super(TestExternalPort, self).setUp()
        self.conf = mock.Mock()
        self.conf.external_network_id = 'ext'
        self.conf.max_retries = 3
        self.conf.retry_delay = 1
        self.conf.external_network_id = self.EXTERNAL_NET_ID
        self.router = neutron.Router.from_dict(self.ROUTER)

    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    def test_create(self, client_wrapper):
        mock_client = mock.Mock()
        mock_client.show_router.return_value = {'router': self.ROUTER}
        mock_client.list_ports.return_value = {
            'ports': [self.ROUTER['ports'][0]]
        }
        client_wrapper.return_value = mock_client
        neutron_wrapper = neutron.Neutron(self.conf)
        with mock.patch.object(neutron_wrapper, 'get_network_subnets') as gns:
            gns.return_value = self.SUBNETS
            port = neutron_wrapper.create_router_external_port(self.router)
            self.assertEqual(port.id, self.EXTERNAL_PORT_ID)

    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    def test_create_missing_gateway_port(self, client_wrapper):
        self.conf.retry_delay = 0
        mock_client = mock.Mock()
        router = copy.deepcopy(self.ROUTER)
        router['ports'] = []
        mock_client.show_router.return_value = {'router': router}
        mock_client.list_ports.return_value = {'ports': []}

        client_wrapper.return_value = mock_client
        neutron_wrapper = neutron.Neutron(self.conf)
        with mock.patch.object(neutron_wrapper, 'get_network_subnets') as gns:
            gns.return_value = self.SUBNETS
            self.assertRaises(
                neutron.RouterGatewayMissing,
                neutron_wrapper.create_router_external_port,
                self.router
            )

    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    def test_missing_v4(self, client_wrapper):
        mock_client = mock.Mock()

        router = copy.deepcopy(self.ROUTER)
        del router['ports'][0]['fixed_ips'][0]

        mock_client.list_ports.return_value = {
            'ports': [router['ports'][0]]
        }

        mock_client.show_router.return_value = {'router': router}
        client_wrapper.return_value = mock_client
        neutron_wrapper = neutron.Neutron(self.conf)
        with mock.patch.object(neutron_wrapper, 'get_network_subnets') as gns:
            gns.return_value = self.SUBNETS
            try:
                neutron_wrapper.create_router_external_port(self.router)
            except neutron.MissingIPAllocation as e:
                self.assertEqual(4, e.missing[0][0])
            else:
                self.fail('Should have seen MissingIPAllocation')

    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    def test_missing_v6(self, client_wrapper):
        mock_client = mock.Mock()

        router = copy.deepcopy(self.ROUTER)
        del router['ports'][0]['fixed_ips'][1]

        mock_client.list_ports.return_value = {
            'ports': [router['ports'][0]]
        }

        mock_client.show_router.return_value = {'router': router}
        client_wrapper.return_value = mock_client
        neutron_wrapper = neutron.Neutron(self.conf)
        with mock.patch.object(neutron_wrapper, 'get_network_subnets') as gns:
            gns.return_value = self.SUBNETS
            try:
                neutron_wrapper.create_router_external_port(self.router)
            except neutron.MissingIPAllocation as e:
                self.assertEqual(6, e.missing[0][0])
            else:
                self.fail('Should have seen MissingIPAllocation')

    @mock.patch('astara.api.neutron.AstaraExtClientWrapper')
    def test_missing_both(self, client_wrapper):
        mock_client = mock.Mock()

        router = copy.deepcopy(self.ROUTER)
        router['ports'][0]['fixed_ips'] = []

        mock_client.show_router.return_value = {'router': router}
        mock_client.list_ports.return_value = {
            'ports': [router['ports'][0]]
        }

        client_wrapper.return_value = mock_client

        neutron_wrapper = neutron.Neutron(self.conf)
        with mock.patch.object(neutron_wrapper, 'get_network_subnets') as gns:
            gns.return_value = self.SUBNETS
            try:
                neutron_wrapper.create_router_external_port(self.router)
            except neutron.MissingIPAllocation as e:
                self.assertEqual(4, e.missing[0][0])
                self.assertEqual(6, e.missing[1][0])
            else:
                self.fail('Should have seen MissingIPAllocation')


class TestLocalServicePorts(base.RugTestBase):
    def setUp(self):
        super(TestLocalServicePorts, self).setUp()
        self.config(external_network_id='fake_extnet_network_id')
        self.config(external_subnet_id='fake_extnet_subnet_id')
        self.config(external_prefix='172.16.77.0/24')
        self.config(management_network_id='fake_mgtnet_network_id')
        self.config(management_subnet_id='fake_mgtnet_subnet_id')
        self.config(management_prefix='172.16.77.0/24')
        self.config(management_prefix='fdca:3ba5:a17a:acda::/64')
        self.neutron_wrapper = neutron.Neutron(cfg.CONF)
        self.fake_interface_driver = mock.Mock(
            plug=mock.Mock(),
            init_l3=mock.Mock(),
            get_device_name=mock.Mock())

    def test_ensure_local_external_port(self):
        with mock.patch.object(self.neutron_wrapper,
                               '_ensure_local_port') as ep:
            self.neutron_wrapper.ensure_local_external_port()
            ep.assert_called_with(
                'fake_extnet_network_id',
                'fake_extnet_subnet_id',
                '172.16.77.0/24',
                'external',
            )

    def test_ensure_local_service_port(self):
        with mock.patch.object(self.neutron_wrapper,
                               '_ensure_local_port') as ep:
            self.neutron_wrapper.ensure_local_service_port()
            ep.assert_called_with(
                'fake_mgtnet_network_id',
                'fake_mgtnet_subnet_id',
                'fdca:3ba5:a17a:acda::/64',
                'service',
            )

    @mock.patch('astara.api.neutron.ip_lib')
    @mock.patch('astara.api.neutron.uuid')
    @mock.patch('astara.api.neutron.importutils')
    def test__ensure_local_port_neutron_port_exists(self, fake_import,
                                                    fake_uuid, fake_ip_lib):
        fake_ip_lib.device_exists.return_value = True
        fake_uuid.uuid5.return_value = 'fake_host_id'
        fake_import.import_object.return_value = self.fake_interface_driver

        fake_port = fakes.fake_port()
        fake_port_dict = {
            'ports': [fake_port._neutron_port_dict],
        }
        fake_client = mock.Mock(
            list_ports=mock.Mock(return_value=fake_port_dict)
        )
        self.neutron_wrapper.api_client = fake_client
        self.fake_interface_driver.get_device_name.return_value = 'fake_dev'

        self.neutron_wrapper._ensure_local_port(
            'fake_network_id',
            'fake_subnet_id',
            'fdca:3ba5:a17a:acda:f816:3eff:fe2b::1/64',
            'service')

        exp_query = {
            'network_id': 'fake_network_id',
            'device_owner': 'network:astara',
            'name': 'ASTARA:RUG:SERVICE',
            'device_id': 'fake_host_id'
        }
        fake_client.list_ports.assert_called_with(**exp_query)
        self.fake_interface_driver.init_l3.assert_called_with(
            'fake_dev', ['fdca:3ba5:a17a:acda:f816:3eff:fe2b:ced0/64']
        )

    @mock.patch('astara.api.neutron.socket')
    @mock.patch('astara.api.neutron.ip_lib')
    @mock.patch('astara.api.neutron.uuid')
    @mock.patch('astara.api.neutron.importutils')
    def test__ensure_local_port_no_neutron_port(self, fake_import, fake_uuid,
                                                fake_ip_lib, fake_socket):
        fake_socket.gethostname.return_value = 'foo_hostname'
        fake_ip_lib.device_exists.return_value = True
        fake_uuid.uuid5.return_value = 'fake_host_id'
        fake_import.import_object.return_value = self.fake_interface_driver

        fake_created_port = {'port': fakes.fake_port().to_dict()}
        fake_client = mock.Mock(
            list_ports=mock.Mock(return_value={'ports': []}),
            create_port=mock.Mock(return_value=fake_created_port))
        self.neutron_wrapper.api_client = fake_client
        self.fake_interface_driver.get_device_name.return_value = 'fake_dev'

        self.neutron_wrapper._ensure_local_port(
            'fake_network_id',
            'fake_subnet_id',
            'fdca:3ba5:a17a:acda:f816:3eff:fe2b::1/64',
            'service')

        exp_port_create_dict = {'port': {
            'admin_state_up': True,
            'binding:host_id': 'foo_hostname',
            'device_id': 'fake_host_id',
            'device_owner': 'network:router_interface',
            'fixed_ips': [{'subnet_id': 'fake_subnet_id'}],
            'name': 'ASTARA:RUG:SERVICE',
            'network_id': 'fake_network_id'
        }}
        fake_client.create_port.assert_called_with(exp_port_create_dict)
        self.fake_interface_driver.init_l3.assert_called_with(
            'fake_dev', ['fdca:3ba5:a17a:acda:f816:3eff:fe2b:ced0/64']
        )

    @mock.patch('time.sleep')
    @mock.patch('astara.api.neutron.ip_lib')
    @mock.patch('astara.api.neutron.uuid')
    @mock.patch('astara.api.neutron.importutils')
    def test__ensure_local_port_plug(self, fake_import,
                                     fake_uuid, fake_ip_lib, fake_sleep):
        fake_ip_lib.device_exists.return_value = False
        fake_uuid.uuid5.return_value = 'fake_host_id'
        fake_import.import_object.return_value = self.fake_interface_driver

        fake_port = fakes.fake_port()
        fake_port_dict = {
            'ports': [fake_port._neutron_port_dict],
        }
        fake_client = mock.Mock(
            list_ports=mock.Mock(return_value=fake_port_dict)
        )
        self.neutron_wrapper.api_client = fake_client
        self.fake_interface_driver.get_device_name.return_value = 'fake_dev'

        self.neutron_wrapper._ensure_local_port(
            'fake_network_id',
            'fake_subnet_id',
            'fdca:3ba5:a17a:acda:f816:3eff:fe2b::1/64',
            'service')

        self.fake_interface_driver.plug.assert_called_with(
            'fake_network_id',
            fake_port.id,
            'fake_dev',
            fake_port.mac_address)
