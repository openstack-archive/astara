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


import netaddr

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from astara.common.i18n import _LI, _LW
from astara.api.config import common

LOG = logging.getLogger(__name__)

DEFAULT_AS = 64512

OPTIONS = [
    cfg.StrOpt('provider_rules_path',
               default='/etc/astara/provider_rules.json'),
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


def build_config(worker_context, router, management_port, interfaces):
    provider_rules = load_provider_rules(cfg.CONF.provider_rules_path)

    networks = generate_network_config(
        worker_context.neutron,
        router,
        management_port,
        interfaces
    )
    gateway = get_default_v4_gateway(
        worker_context.neutron, router, networks)

    return {
        'asn': cfg.CONF.asn,
        'neighbor_asn': cfg.CONF.neighbor_asn,
        'default_v4_gateway': gateway,
        'networks': networks,
        'labels': provider_rules.get('labels', {}),
        'floating_ips': generate_floating_config(router),
        'tenant_id': router.tenant_id,
        'hostname': 'ak-%s' % router.tenant_id,
        'orchestrator': worker_context.config,
        'vpn': generate_vpn_config(router, worker_context.neutron)
    }


def get_default_v4_gateway(client, router, networks):
    """Find the IPv4 default gateway for the router.
    """
    LOG.debug('networks = %r', networks)
    if router.external_port:
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
    LOG.info(_LI('%s: no default gateway was found'), router.id)
    return ''


def load_provider_rules(path):
    try:
        return jsonutils.load(open(path))
    except:  # pragma nocover
        LOG.warning(_LW('unable to open provider rules: %s'), path)
        return {}


def generate_network_config(client, router, management_port, iface_map):
    retval = [
        common.network_config(
            client,
            management_port,
            iface_map[management_port.network_id],
            MANAGEMENT_NET
        )
    ]

    if router.external_port:
        retval.extend([
            common.network_config(
                client,
                router.external_port,
                iface_map[router.external_port.network_id],
                EXTERNAL_NET)])

    retval.extend(
        common.network_config(
            client,
            p,
            iface_map[p.network_id],
            INTERNAL_NET,
            client.get_network_ports(p.network_id))
        for p in router.internal_ports)

    return retval


def generate_floating_config(router):
    return [
        {'floating_ip': str(fip.floating_ip), 'fixed_ip': str(fip.fixed_ip)}
        for fip in router.floating_ips
    ]


def generate_vpn_config(router, client):
    if not cfg.CONF.router.ipsec_vpn:
        return {}

    return {
        'ipsec': [
            v.to_dict() for v in client.get_vpnservices_for_router(router.id)
        ]
    }
