import logging
import re

import netaddr
from oslo.config import cfg

from akanda.rug.openstack.common import jsonutils

LOG = logging.getLogger(__name__)

OPTIONS = [
    cfg.StrOpt('provider_rules_path')
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

    return {
        'networks': generate_network_config(client, router, interfaces),
        'address_book': generate_address_book_config(client, router),
        'anchors': generate_anchor_config(client, provider_rules, router),
        'labels': provider_rules.get('labels', {}),
        'floating_ips': generate_floating_config(router)
    }


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
            interface = iface
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
        'dhcp_enabled': subnet.enable_dhcp,
        'dns_nameservers': subnet.dns_nameservers,
        'host_routes': subnet.host_routes,
        'gateway_ip': str(subnet.gateway_ip)
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


def generate_address_book_config(client, router):
    return dict([(g.name, [str(e) for e in g.entries])
                 for g in client.get_addressgroups(router.tenant_id)])


def generate_anchor_config(client, provider_rules, router):
    retval = provider_rules.get('preanchors', [])

    retval.extend([
        generate_tenant_port_forward_anchor(client, router),
        generate_tenant_filter_rule_anchor(client, router)
    ])
    retval.extend(provider_rules.get('postanchors', []))

    return retval


def generate_tenant_port_forward_anchor(client, router):
    to_ip = router.external_port.first_v4 or INVALID_IP

    rules = [_format_port_forward_rule(to_ip, pf)
             for pf in client.get_portforwards(router.tenant_id)]

    return {
        'name': 'tenant_v4_portforwards',
        'rules': [r for r in rules if r]
    }


def _format_port_forward_rule(to_ip, pf):
    redirect_ip = pf.port.first_v4 or INVALID_IP

    if not redirect_ip:
        return

    return {
        'action': 'pass',
        'direction': 'in',
        'family': 'inet',
        'protocol': pf.protocol,
        'destination': '%s/32' % to_ip,
        'destination_port': pf.public_port,
        'redirect': redirect_ip,
        'redirect_port': pf.private_port
    }


def generate_tenant_filter_rule_anchor(client, router):
    return {
        'name': 'tenant_filterrules',
        'rules': [_format_filter_rule(r)
                  for r in client.get_filterrules(router.tenant_id)]
    }


def _format_filter_rule(rule):
    return {
        'action': rule.action,
        'protocol': rule.protocol,
        'source': rule.source.name if rule.source else None,
        'source_port': rule.source_port,
        'destination': rule.destination.name if rule.destination else None,
        'destination_port': rule.destination_port,
    }


def generate_floating_config(router):
    return [
        {'floating_ip': str(fip.floating_ip), 'fixed_ip': str(fip.fixed_ip)}
        for fip in router.floating_ips
    ]
