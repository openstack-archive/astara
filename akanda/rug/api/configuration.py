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


import logging
import re

import netaddr
from oslo.config import cfg

from akanda.rug.openstack.common import jsonutils

LOG = logging.getLogger(__name__)

DEFAULT_AS = 64512

OPTIONS = [
    cfg.StrOpt('provider_rules_path'),
    cfg.IntOpt('asn', default=DEFAULT_AS),
    cfg.IntOpt('neighbor_asn', default=DEFAULT_AS),
]

cfg.CONF.register_opts(OPTIONS)

EXTERNAL_NET = 'external'
INTERNAL_NET = 'internal'
MANAGEMENT_NET = 'management'
SERVICE_STATIC = 'static'
SERVICE_DHCP = 'dhcp'
SERVICE_RA = 'ra'


def build_config(client, router, interfaces):
    provider_rules = load_provider_rules(cfg.CONF.provider_rules_path)

    networks = generate_network_config(client, router, interfaces)
    gateway = get_default_v4_gateway(client, router, networks)

    return {
        'asn': cfg.CONF.asn,
        'neighbor_asn': cfg.CONF.neighbor_asn,
        'default_v4_gateway': gateway,
        'networks': networks,
        'labels': provider_rules.get('labels', {}),
        'floating_ips': generate_floating_config(router),
        'tenant_id': router.tenant_id,
        'hostname': router.name
    }


def get_default_v4_gateway(client, router, networks):
    """Find the IPv4 default gateway for the router.
    """
    LOG.debug('networks = %r', networks)
    LOG.debug('external interface = %s', router.external_port.mac_address)

    # Now find the subnet that our external IP is on, and return its
    # gateway.
    for n in networks:
        if n['network_type'] == EXTERNAL_NET:
            v4_addresses = [
                addr
                for addr in (netaddr.IPAddress(ip.partition('/')[0])
                             for ip in n['interface']['addresses'])
                if addr.version == 4
            ]
            for s in n['subnets']:
                subnet = netaddr.IPNetwork(s['cidr'])
                if subnet.version != 4:
                    continue
                LOG.debug(
                    '%s: checking if subnet %s should have the default route',
                    router.id, s['cidr'])
                for addr in v4_addresses:
                    if addr in subnet:
                        LOG.debug(
                            '%s: found gateway %s for subnet %s on network %s',
                            router.id,
                            s['gateway_ip'],
                            s['cidr'],
                            n['network_id'],
                        )
                        return s['gateway_ip']

    # Sometimes we are asked to build a configuration for the server
    # when the external interface is still marked as "down". We can
    # report that case, but we don't treat it as an error here because
    # we'll be asked to do it again when the interface comes up.
    LOG.info('%s: no default gateway was found', router.id)
    return ''


def load_provider_rules(path):
    try:
        return jsonutils.load(open(path))
    except:  # pragma nocover
        LOG.exception('unable to open provider rules: %s' % path)


def generate_network_config(client, router, interfaces):
    iface_map = dict((i['lladdr'], i['ifname']) for i in interfaces)

    retval = [
        _network_config(
            client,
            router.external_port,
            iface_map[router.external_port.mac_address],
            EXTERNAL_NET),
        _management_network_config(
            router.management_port,
            iface_map[router.management_port.mac_address],
            interfaces,
        )]

    retval.extend(
        _network_config(
            client,
            p,
            iface_map[p.mac_address],
            INTERNAL_NET,
            client.get_network_ports(p.network_id))
        for p in router.internal_ports)

    return retval


def _management_network_config(port, ifname, interfaces):
    for iface in interfaces:
        if iface['ifname'] == ifname:
            return _make_network_config_dict(
                iface, MANAGEMENT_NET, port.network_id)


def _network_config(client, port, ifname, network_type, network_ports=[]):
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


def generate_floating_config(router):
    return [
        {'floating_ip': str(fip.floating_ip), 'fixed_ip': str(fip.fixed_ip)}
        for fip in router.floating_ips
    ]
