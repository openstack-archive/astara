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

import netaddr

from astara.api.neutron import Subnet


class FakeModel(object):
    def __init__(self, id_, **kwargs):
        self.id = id_
        self.__dict__.update(kwargs)


fake_fixed_ip = FakeModel(
    '1',
    ip_address='9.9.9.9',
    subnet_id='s1')


fake_ext_port = FakeModel(
    '1',
    mac_address='aa:bb:cc:dd:ee:ff',
    network_id='ext-net',
    fixed_ips=[fake_fixed_ip],
    first_v4='9.9.9.9',
    device_id='e-e-e-e')


fake_mgt_port = FakeModel(
    '2',
    name='ASTARA:MGT:foo',
    mac_address='aa:bb:cc:cc:bb:aa',
    network_id='mgt-net',
    device_id='m-m-m-m')

fake_int_port = FakeModel(
    '3',
    name='ASTARA:RUG:foo',
    mac_address='aa:aa:aa:aa:aa:aa',
    network_id='int-net',
    fixed_ips=[fake_fixed_ip],
    device_id='i-i-i-i')

fake_instance_port = FakeModel(
    '4',
    name='foo',
    mac_address='aa:aa:aa:aa:aa:bb',
    network_id='int-net',
    fixed_ips=[FakeModel('', ip_address='192.168.1.2', subnet_id='s1')],
    first_v4='192.168.1.2',
    device_id='v-v-v-v')

fake_instance_mgt_port = FakeModel(
    '4',
    name='ASTARA:MGT:foo',
    mac_address='aa:aa:aa:aa:aa:bb',
    network_id='int-net',
    fixed_ips=[FakeModel('', ip_address='192.168.1.2', subnet_id='s1')],
    first_v4='192.168.1.2',
    device_id='v-v-v-v')

fake_instance_vrrp_port = FakeModel(
    '4',
    name='ASTARA:VRRP:foo',
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

fake_network = FakeModel(
    'fake_network_id',
    name='thenet',
    tenant_id='tenant_id',
    status='ACTIVE',
    shared=False,
    admin_statue_up=True,
    mtu=1280,
    port_security_enabled=False,
    subnets=[fake_subnet]
)

fake_router = FakeModel(
    'router_id',
    tenant_id='tenant_id',
    name='router_name',
    external_port=fake_ext_port,
    management_port=fake_mgt_port,
    internal_ports=[fake_int_port],
    ha=False)
