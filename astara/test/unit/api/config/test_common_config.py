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
import unittest2 as unittest

from astara.api.config import common

from astara.test.unit.api.config import config_fakes as fakes


class TestCommonConfig(unittest.TestCase):
    def test_network_config(self):
        mock_client = mock.Mock()
        mock_client.get_network_detail.return_value = fakes.fake_network
        subnets_dict = {fakes.fake_subnet.id: fakes.fake_subnet}

        fake_fixed_ip = fakes.fake_fixed_ip
        fake_port = fakes.fake_int_port

        with mock.patch.object(common, '_make_network_config_dict') as nc:
            with mock.patch.object(common, '_interface_config') as ic:
                mock_interface = mock.Mock()
                ic.return_value = mock_interface

                common.network_config(
                    mock_client,
                    fake_port,
                    'ge1',
                    'internal',
                    [])

                ic.assert_called_once_with(
                    'ge1', [fake_fixed_ip], subnets_dict, 1280)
                nc.assert_called_once_with(
                    mock_interface,
                    'internal',
                    'int-net',
                    mtu=1280,
                    subnets_dict=subnets_dict,
                    network_ports=[]),

    def test_make_network_config(self):
        interface = {'ifname': 'ge2'}

        result = common._make_network_config_dict(
            interface,
            'internal',
            fakes.fake_int_port.network_id,
            1280,
            'dhcp',
            'ra',
            subnets_dict={fakes.fake_subnet.id: fakes.fake_subnet},
            network_ports=[fakes.fake_instance_port])

        expected = {
            'interface': interface,
            'network_id': fakes.fake_int_port.network_id,
            'v4_conf_service': 'dhcp',
            'v6_conf_service': 'ra',
            'network_type': 'internal',
            'mtu': 1280,
            'subnets': [{'cidr': '192.168.1.0/24',
                         'dhcp_enabled': True,
                         'dns_nameservers': ['8.8.8.8'],
                         'gateway_ip': '192.168.1.1',
                         'host_routes': {},
                         'id': 's1'}],
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
        ip = '%s/%s' % (
            fakes.fake_fixed_ip.ip_address,
            fakes.fake_subnet.cidr.prefixlen)
        expected = {
            'addresses': [ip],
            'ifname': 'ge1',
            'mtu': 1280
        }
        subnets_dict = {fakes.fake_fixed_ip.subnet_id: fakes.fake_subnet}

        self.assertEqual(
            expected,
            common._interface_config(
                ifname='ge1',
                fixed_ips=[fakes.fake_fixed_ip],
                subnets_dict=subnets_dict,
                mtu=1280
            )
        )

    def test_subnet_config(self):
        expected = {
            'cidr': '192.168.1.0/24',
            'dhcp_enabled': True,
            'dns_nameservers': ['8.8.8.8'],
            'gateway_ip': '192.168.1.1',
            'host_routes': {},
            'id': 's1',
        }
        self.assertEqual(common._subnet_config(fakes.fake_subnet), expected)

    def test_subnet_config_with_slaac_enabled(self):
        expected = {
            'cidr': 'fdee:9f85:83be::/48',
            'dhcp_enabled': False,
            'dns_nameservers': ['8.8.8.8'],
            'gateway_ip': 'fdee:9f85:83be::1',
            'host_routes': {},
            'id': 'fake_id',
        }
        self.assertEqual(
            common._subnet_config(fakes.fake_subnet_with_slaac), expected)

    def test_subnet_config_no_gateway(self):
        expected = {
            'cidr': '192.168.1.0/24',
            'dhcp_enabled': True,
            'dns_nameservers': ['8.8.8.8'],
            'gateway_ip': '',
            'host_routes': {},
            'id': 's1',
        }
        sn = fakes.FakeModel(
            's1',
            cidr=netaddr.IPNetwork('192.168.1.0/24'),
            gateway_ip='',
            enable_dhcp=True,
            dns_nameservers=['8.8.8.8'],
            ipv6_ra_mode='',
            host_routes={})
        self.assertEqual(common._subnet_config(sn), expected)

    def test_subnet_config_gateway_none(self):
        expected = {
            'cidr': '192.168.1.0/24',
            'dhcp_enabled': True,
            'dns_nameservers': ['8.8.8.8'],
            'gateway_ip': '',
            'host_routes': {},
            'id': 's1',
        }
        sn = fakes.FakeModel(
            's1',
            cidr=netaddr.IPNetwork('192.168.1.0/24'),
            gateway_ip=None,
            enable_dhcp=True,
            dns_nameservers=['8.8.8.8'],
            ipv6_ra_mode='',
            host_routes={})
        self.assertEqual(common._subnet_config(sn), expected)

    def test_allocation_config_vrrp(self):
        subnets_dict = {fakes.fake_subnet.id: fakes.fake_subnet}
        self.assertEqual(
            common._allocation_config(
                [fakes.fake_instance_vrrp_port],
                subnets_dict),
            []
        )

    def test_allocation_config_mgt(self):
        subnets_dict = {fakes.fake_subnet.id: fakes.fake_subnet}
        expected = [
            {'mac_address': 'aa:aa:aa:aa:aa:bb',
             'ip_addresses': {'192.168.1.2': True},
             'hostname': '192-168-1-2.local',
             'device_id': 'v-v-v-v'}
        ]
        self.assertEqual(
            common._allocation_config([
                fakes.fake_instance_mgt_port],
                subnets_dict),
            expected
        )
