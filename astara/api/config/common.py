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


import re

from oslo_log import log as logging

LOG = logging.getLogger(__name__)

SERVICE_STATIC = 'static'


def network_config(client, port, ifname, network_type, network_ports=[]):
    subnets = client.get_network_subnets(port.network_id)
    subnets_dict = dict((s.id, s) for s in subnets)
    return _make_network_config_dict(
        _interface_config(ifname, port, subnets_dict),
        network_type,
        port.network_id,
        subnets_dict=subnets_dict,
        network_ports=network_ports)


def _make_network_config_dict(interface, network_type, network_id,
                              v4_conf=SERVICE_STATIC, v6_conf=SERVICE_STATIC,
                              subnets_dict={}, network_ports=[]):
    return {'interface': interface,
            'network_id': network_id,
            'v4_conf_service': v4_conf,
            'v6_conf_service': v6_conf,
            'network_type': network_type,
            'subnets': [_subnet_config(s) for s in subnets_dict.values()],
            'allocations': _allocation_config(network_ports, subnets_dict)}


def _interface_config(ifname, port, subnets_dict):
    def fmt(fixed):
        return '%s/%s' % (fixed.ip_address,
                          subnets_dict[fixed.subnet_id].cidr.prefixlen)

    return {'ifname': ifname,
            'addresses': [fmt(fixed) for fixed in port.fixed_ips]}


def _subnet_config(subnet):
    return {
        'cidr': str(subnet.cidr),
        'dhcp_enabled': subnet.enable_dhcp and subnet.ipv6_ra_mode != 'slaac',
        'dns_nameservers': subnet.dns_nameservers,
        'host_routes': subnet.host_routes,
        'gateway_ip': (str(subnet.gateway_ip)
                       if subnet.gateway_ip is not None
                       else ''),
    }


def _allocation_config(ports, subnets_dict):
    r = re.compile('[:.]')
    allocations = []

    for port in ports:
        if port.name.startswith('ASTARA:VRRP:'):
            continue

        addrs = {
            str(fixed.ip_address): subnets_dict[fixed.subnet_id].enable_dhcp
            for fixed in port.fixed_ips
        }

        if not addrs:
            continue

        allocations.append(
            {
                'ip_addresses': addrs,
                'device_id': port.device_id,
                'hostname': '%s.local' % r.sub('-', sorted(addrs.keys())[0]),
                'mac_address': port.mac_address
            }
        )

    return allocations
