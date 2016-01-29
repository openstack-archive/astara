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


import collections
import itertools
import socket
import time
import uuid

import netaddr
import six

from neutronclient.v2_0 import client
from neutronclient.common import exceptions as neutron_exc

from oslo_config import cfg
from oslo_context import context
from oslo_log import log as logging
from oslo_utils import importutils

from astara.common.i18n import _, _LI, _LW
from astara.common.linux import ip_lib
from astara.api import keystone
from astara.common import rpc

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


neutron_opts = [
    cfg.StrOpt('management_network_id'),
    cfg.StrOpt('external_network_id'),
    cfg.StrOpt('management_subnet_id'),
    cfg.StrOpt('external_subnet_id'),
    cfg.StrOpt('management_prefix', default='fdca:3ba5:a17a:acda::/64'),
    cfg.StrOpt('external_prefix', default='172.16.77.0/24'),
    cfg.IntOpt('astara_mgt_service_port', default=5000),
    cfg.StrOpt('default_instance_flavor', default=1),
    cfg.StrOpt('interface_driver',
               default='astara.common.linux.interface.OVSInterfaceDriver'),
    cfg.BoolOpt('neutron_port_security_extension_enabled', default=True),

    # legacy_fallback option is deprecated and will be removed in the N-release
    cfg.BoolOpt('legacy_fallback_mode', default=True,
                help=_('Check for resources using the Liberty naming scheme '
                       'when the modern name does not exist.'))
]
CONF.register_opts(neutron_opts)


# copied from Neutron source
DEVICE_OWNER_ROUTER_MGT = "network:router_management"
DEVICE_OWNER_ROUTER_INT = "network:router_interface"
DEVICE_OWNER_ROUTER_GW = "network:router_gateway"
DEVICE_OWNER_FLOATINGIP = "network:floatingip"
DEVICE_OWNER_RUG = "network:astara"

PLUGIN_ROUTER_RPC_TOPIC = 'q-l3-plugin'

STATUS_ACTIVE = 'ACTIVE'
STATUS_BUILD = 'BUILD'
STATUS_DOWN = 'DOWN'
STATUS_ERROR = 'ERROR'

# Service operation status constants
# Copied from neutron.plugings.common.constants.py
# prefaced here with PLUGIN_
PLUGIN_ACTIVE = "ACTIVE"
PLUGIN_DOWN = "DOWN"
PLUGIN_CREATED = "CREATED"
PLUGIN_PENDING_CREATE = "PENDING_CREATE"
PLUGIN_PENDING_UPDATE = "PENDING_UPDATE"
PLUGIN_PENDING_DELETE = "PENDING_DELETE"
PLUGIN_INACTIVE = "INACTIVE"
PLUGIN_ERROR = "ERROR"

# XXX not sure these are needed?
ACTIVE_PENDING_STATUSES = (
    PLUGIN_ACTIVE,
    PLUGIN_PENDING_CREATE,
    PLUGIN_PENDING_UPDATE
)


class RouterGone(Exception):
    pass


class LoadBalancerGone(Exception):
    pass


class RouterGatewayMissing(Exception):
    pass


class MissingIPAllocation(Exception):

    def __init__(self, port_id, missing=None):
        self.port_id = port_id
        self.missing = missing
        msg = 'Port %s missing expected IPs ' % port_id
        if missing:
            ip_msg = ' and '.join(
                ('IPv%s address from one of %s' %
                 (mv, missing_subnets))
                for mv, missing_subnets in missing
            )
            msg = msg + ip_msg
        super(MissingIPAllocation, self).__init__(msg)


class DictModelBase(object):
    DICT_ATTRS = ()

    def __repr__(self):
        return '<%s (%s:%s)>' % (self.__class__.__name__,
                                 getattr(self, 'name', ''),
                                 getattr(self, 'tenant_id', ''))

    def __eq__(self, other):
        return type(self) == type(other) and vars(self) == vars(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def to_dict(self):
        """Serialize the object into a dict, handy for building config"""
        d = {}
        for attr in self.DICT_ATTRS:
            val = getattr(self, attr)
            if isinstance(val, list):
                # this'll eventually break something and you can find this
                # comment and hurt me.
                val = [v.to_dict() for v in val]
            if hasattr(val, 'to_dict'):
                val = val.to_dict()
            if isinstance(val, netaddr.IPAddress):
                val = str(val)
            d[attr] = val
        return d


class Router(object):
    def __init__(self, id_, tenant_id, name, admin_state_up, status,
                 external_port=None, internal_ports=None, floating_ips=None):
        self.id = id_
        self.tenant_id = tenant_id
        self.name = name
        self.admin_state_up = admin_state_up
        self.status = status
        self.external_port = external_port
        self.internal_ports = internal_ports or []
        self.floating_ips = floating_ips or []

    def __repr__(self):
        return '<%s (%s:%s)>' % (self.__class__.__name__,
                                 self.name,
                                 self.tenant_id)

    def __eq__(self, other):
        return type(self) == type(other) and vars(self) == vars(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    @classmethod
    def from_dict(cls, d):
        external_port = None
        internal_ports = []

        if d.get('gw_port'):
            external_port = Port.from_dict(d.get('gw_port'))

        for port_dict in d.get('_interfaces', []):
            port = Port.from_dict(port_dict)
            if port.device_owner == DEVICE_OWNER_ROUTER_INT:
                internal_ports.append(port)

        fips = [FloatingIP.from_dict(fip) for fip in d.get('_floatingips', [])]

        return cls(
            d['id'],
            d['tenant_id'],
            d['name'],
            d['admin_state_up'],
            d['status'],
            external_port,
            internal_ports,
            floating_ips=fips,
        )

    @property
    def ports(self):
        return itertools.chain(
            [self.external_port],
            self.internal_ports
        )


class Network(DictModelBase):
    DICT_ATTRS = ('id', 'name', 'tenant_id', 'status', 'shared',
                  'admin_state_up', 'mtu', 'port_security_enabled')

    def __init__(self, id_, name, tenant_id, status, shared, admin_state_up,
                 mtu=None, port_security_enabled=False, subnets=()):
        self.id = id_
        self.name = name
        self.tenant_id = tenant_id
        self.shared = shared
        self.admin_state_up = admin_state_up
        self.mtu = mtu
        self.port_security_enabled = port_security_enabled
        self.subnets = subnets

    @classmethod
    def from_dict(cls, d):
        optional = {}

        for opt in ['mtu', 'port_security_enabled']:
            if opt in d:
                optional[opt] = d[opt]

        return cls(
            d['id'],
            d['name'],
            d['tenant_id'],
            d['status'],
            d['shared'],
            d['admin_state_up'],
            **optional
        )


class Subnet(DictModelBase):
    DICT_ATTRS = ('id', 'name', 'tenant_id', 'network_id', 'ip_version',
                  'cidr', 'gateway_ip', 'enable_dhcp', 'dns_nameservers',
                  'host_routes', 'ipv6_ra_mode')

    def __init__(self, id_, name, tenant_id, network_id, ip_version, cidr,
                 gateway_ip, enable_dhcp, dns_nameservers, host_routes,
                 ipv6_ra_mode):
        self.id = id_
        self.name = name
        self.tenant_id = tenant_id
        self.network_id = network_id
        self.ip_version = ip_version
        try:
            self.cidr = netaddr.IPNetwork(cidr)
        except (TypeError, netaddr.AddrFormatError) as e:
            raise ValueError(
                _('Invalid CIDR %r for subnet %s of network %s: %s') % (
                    cidr, id_, network_id, e,
                )
            )
        try:
            self.gateway_ip = netaddr.IPAddress(gateway_ip)
        except (TypeError, netaddr.AddrFormatError) as e:
            self.gateway_ip = None
            LOG.info(_LI(
                'Bad gateway_ip on subnet %s: %r (%s)'),
                id_, gateway_ip, e)
        self.enable_dhcp = enable_dhcp
        self.dns_nameservers = dns_nameservers
        self.host_routes = host_routes
        self.ipv6_ra_mode = ipv6_ra_mode

    @classmethod
    def from_dict(cls, d):
        return cls(
            d['id'],
            d['name'],
            d['tenant_id'],
            d['network_id'],
            d['ip_version'],
            d['cidr'],
            d['gateway_ip'],
            d['enable_dhcp'],
            d['dns_nameservers'],
            d['host_routes'],
            d['ipv6_ra_mode'])


class Port(DictModelBase):
    DICT_ATTRS = ('id', 'device_id', 'fixed_ips', 'mac_address', 'network_id',
                  'device_owner', 'name')

    def __init__(self, id_, device_id='', fixed_ips=None, mac_address='',
                 network_id='', device_owner='', name='',
                 neutron_port_dict=None):
        self.id = id_
        self.device_id = device_id
        self.fixed_ips = fixed_ips or []
        self.mac_address = mac_address
        self.network_id = network_id
        self.device_owner = device_owner
        self.name = name

        # Unlike instance ports, management ports are created at boot and
        # could be created on the Pez side.  We need to pass that info
        # back to Rug via RPC so hang on to the original port data for
        # easier serialization, allowing Rug to re-create (via from_dict).
        # without another neutron call.
        self._neutron_port_dict = neutron_port_dict or {}

    def __eq__(self, other):
        return type(self) == type(other) and vars(self) == vars(other)

    @property
    def first_v4(self):
        for fixed_ip in self.fixed_ips:
            ip = netaddr.IPAddress(fixed_ip.ip_address)
            if ip.version == 4:
                return str(ip)
        return None

    @classmethod
    def from_dict(cls, d):
        return cls(
            d['id'],
            d['device_id'],
            fixed_ips=[FixedIp.from_dict(fip) for fip in d['fixed_ips']],
            mac_address=d['mac_address'],
            network_id=d['network_id'],
            device_owner=d['device_owner'],
            name=d['name'],
            neutron_port_dict=d)

    def to_dict(self):
        return self._neutron_port_dict


class FixedIp(DictModelBase):
    DICT_ATTRS = ('subnet_id', 'ip_address')

    def __init__(self, subnet_id, ip_address):
        self.subnet_id = subnet_id
        self.ip_address = netaddr.IPAddress(ip_address)

    def __eq__(self, other):
        return type(self) == type(other) and vars(self) == vars(other)

    @classmethod
    def from_dict(cls, d):
        return cls(d['subnet_id'], d['ip_address'])


class FloatingIP(object):
    def __init__(self, id_, floating_ip, fixed_ip):
        self.id = id_
        self.floating_ip = netaddr.IPAddress(floating_ip)
        self.fixed_ip = netaddr.IPAddress(fixed_ip)

    @classmethod
    def from_dict(cls, d):
        return cls(
            d['id'],
            d['floating_ip_address'],
            d['fixed_ip_address']
        )


class LoadBalancer(DictModelBase):
    DICT_ATTRS = ('id', 'tenant_id', 'name', 'admin_state_up', 'status',
                  'listeners', 'vip_address', 'vip_port')

    def __init__(self, id_, tenant_id, name, admin_state_up, status,
                 vip_address=None, vip_port=None, listeners=()):
        self.id = id_
        self.tenant_id = tenant_id
        self.name = name
        self.admin_state_up = admin_state_up
        self.status = status
        self.vip_address = vip_address
        self.vip_port = vip_port
        self.listeners = listeners

    @property
    def ports(self):
        if self.vip_port:
            return [self.vip_port]
        else:
            return []

    @classmethod
    def from_dict(cls, d):
        if d.get('vip_port'):
            vip_port = Port.from_dict(d.get('vip_port'))
            vip_address = d['vip_address']
        else:
            vip_port = None
            vip_address = None
        return cls(
            d['id'],
            d['tenant_id'],
            d['name'],
            d['admin_state_up'],
            d['provisioning_status'],
            vip_address,
            vip_port,
            [Listener.from_dict(l) for l in d.get('listeners')],
        )


class Listener(DictModelBase):
    DICT_ATTRS = ('id', 'tenant_id', 'name', 'admin_state_up', 'protocol',
                  'protocol_port', 'default_pool')

    def __init__(self, id_, tenant_id, name, admin_state_up, protocol,
                 protocol_port, default_pool=None):
        self.id = id_
        self.tenant_id = tenant_id
        self.name = name
        self.admin_state_up = admin_state_up
        self.protocol = protocol
        self.protocol_port = protocol_port
        self.default_pool = default_pool

    @classmethod
    def from_dict(cls, d):
        # NOTE: we may be constructing a loadbalancer without the full
        # details during pre-populate.  To avoid having to do more neutron
        # calls to find the additional data, support instantiation without
        # full details.
        return cls(
            d['id'],
            d.get('tenant_id'),
            d.get('name'),
            d.get('admin_state_up'),
            d.get('protocol'),
            d.get('protocol_port'),
        )


class Pool(DictModelBase):
    DICT_ATTRS = (
        'id', 'tenant_id', 'name', 'admin_state_up', 'lb_algorithm',
        'protocol', 'healthmonitor', 'session_persistence', 'members'
    )

    def __init__(self, id_, tenant_id, name, admin_state_up, lb_algorithm,
                 protocol, healthmonitor=None, session_persistence=None,
                 members=()):
        self.id = id_
        self.tenant_id = tenant_id
        self.name = name
        self.admin_state_up = admin_state_up
        self.lb_algorithm = lb_algorithm
        self.protocol = protocol
        self.healthmonitor = healthmonitor
        self.session_persistence = session_persistence
        self.members = members

    @classmethod
    def from_dict(cls, d):
        return cls(
            d['id'],
            d['tenant_id'],
            d['name'],
            d['admin_state_up'],
            d['lb_algorithm'],
            d['protocol'],
        )


class Member(DictModelBase):
    DICT_ATTRS = ('id', 'tenant_id', 'admin_state_up', 'address',
                  'protocol_port', 'weight', 'subnet')

    def __init__(self, id_, tenant_id, admin_state_up, address, protocol_port,
                 weight, subnet=None):
        self.id = id_
        self.tenant_id = tenant_id
        self.admin_state_up = admin_state_up
        self.address = netaddr.IPAddress(address)
        self.protocol_port = protocol_port
        self.weight = weight
        self.subnet = subnet

    @classmethod
    def from_dict(cls, d):
        return cls(
            d['id'],
            d['tenant_id'],
            d['admin_state_up'],
            d['address'],
            d['protocol_port'],
            d['weight'],
        )


class AstaraExtClientWrapper(client.Client):
    """Add client support for Astara Extensions. """

    routerstatus_path = '/dhrouterstatus'
    lbstatus_path = '/akloadbalancerstatus'

    @client.APIParamsCall
    def update_router_status(self, router, status):
        return self.put(
            '%s/%s' % (self.routerstatus_path, router),
            body={'routerstatus': {'status': status}}
        )

    @client.APIParamsCall
    def update_loadbalancer_status(self, load_balancer, status):
        return self.put(
            '%s/%s' % (self.lbstatus_path, load_balancer),
            # XXX We should be differentiating between these 2 states
            body={
                'loadbalancerstatus': {
                    'provisioning_status': status,
                    'operating_status': status,
                }
            }
        )


class L3PluginApi(object):

    """Agent side of the Qunatum l3 agent RPC API."""

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic, host):
        self.host = host
        self._client = rpc.get_rpc_client(
            topic=topic,
            exchange=cfg.CONF.neutron_control_exchange,
            version=self.BASE_RPC_API_VERSION)

    def get_routers(self, router_id=None):
        """Make a remote process call to retrieve the sync data for routers."""
        router_id = [router_id] if router_id else None
        # yes the plural is intended for havana compliance
        retval = self._client.call(
            context.get_admin_context().to_dict(),
            'sync_routers', host=self.host, router_ids=router_id)  # plural
        return retval


class Neutron(object):
    def __init__(self, conf):
        self.conf = conf
        ks_session = keystone.KeystoneSession()
        self.api_client = AstaraExtClientWrapper(
            session=ks_session.session,
        )
        self.l3_rpc_client = L3PluginApi(PLUGIN_ROUTER_RPC_TOPIC,
                                         cfg.CONF.host)

    def update_loadbalancer_status(self, loadbalancer_id, status):
        try:
            self.api_client.update_loadbalancer_status(loadbalancer_id, status)
        except Exception as e:
            # We don't want to die just because we can't tell neutron
            # what the status of the router should be. Log the error
            # but otherwise ignore it.
            LOG.info(_LI(
                'ignoring failure to update status for %s to %s: %s'),
                id, status, e,
            )

    def get_loadbalancers(self, tenant_id=None):
        if tenant_id:
            res = self.api_client.list_loadbalancers(tenant_id=tenant_id)
        else:
            res = self.api_client.list_loadbalancers()
        return [
            LoadBalancer.from_dict(lb_data) for lb_data in
            res.get('loadbalancers', [])
        ]

    def get_loadbalancer_detail(self, lb_id):
        try:
            lb_data = self.api_client.show_loadbalancer(lb_id)['loadbalancer']
        except neutron_exc.NotFound:
            raise LoadBalancerGone(
                'No load balancer with id %s found.' % lb_id)

        lb = LoadBalancer.from_dict(lb_data)

        lb.vip_port = Port.from_dict(
            self.api_client.show_port(lb_data['vip_port_id'])['port']
        )
        lb.vip_address = lb_data.get('vip_address')
        lb.listeners = [
            self.get_listener_detail(l['id']) for l in lb_data['listeners']
        ]

        return lb

    def get_listener_detail(self, listener_id):
        data = self.api_client.show_listener(listener_id)['listener']
        listener = Listener.from_dict(data)
        if data.get('default_pool_id'):
            listener.default_pool = self.\
                get_pool_detail(data['default_pool_id'])
        return listener

    def get_pool_detail(self, pool_id):
        data = self.api_client.show_lbaas_pool(pool_id)['pool']
        pool = Pool.from_dict(data)
        if data.get('members'):
            pool.members = [self.get_member_detail(pool_id, m['id'])
                            for m in data['members']]
        return pool

    def get_loadbalancer_by_listener(self, listener_id, tenant_id=None):
        for lb in self.get_loadbalancers(tenant_id):
            lbd = self.get_loadbalancer_detail(lb.id)
            if listener_id in [l.id for l in lbd.listeners]:
                return lbd

    def get_loadbalancer_by_member(self, member_id, tenant_id=None):
        for lb in self.get_loadbalancers(tenant_id):
            lbd = self.get_loadbalancer_detail(lb.id)
            for listener in lbd.listeners:
                pd = self.get_pool_detail(listener.default_pool.id)
                if member_id in [m.id for m in pd.members]:
                    return lbd

    def get_member_detail(self, pool_id, member_id):
        data = self.api_client.show_lbaas_member(member_id, pool_id)['member']
        member = Member.from_dict(data)
        return member

    def get_routers(self, detailed=True):
        """Return a list of routers."""
        if detailed:
            return [Router.from_dict(r) for r in
                    self.l3_rpc_client.get_routers()]

        routers = self.api_client.list_routers().get('routers', [])
        return [Router.from_dict(r) for r in routers]

    def get_router_detail(self, router_id):
        """Return detailed information about a router and it's networks."""
        router = self.l3_rpc_client.get_routers(router_id=router_id)
        try:
            return Router.from_dict(router[0])
        except IndexError:
            raise RouterGone(_('the router is no longer available'))

    def get_router_for_tenant(self, tenant_id):
        response = self.api_client.list_routers(tenant_id=tenant_id)
        routers = response.get('routers', [])

        if routers:
            return self.get_router_detail(routers[0]['id'])
        else:
            LOG.debug('found no router for tenant %s', tenant_id)
            LOG.debug('query response: %r', response)
            return None

    def get_network_ports(self, network_id):
        return [Port.from_dict(p) for p in
                self.api_client.list_ports(network_id=network_id)['ports']]

    def get_network_subnets(self, network_id):
        response = []
        subnet_response = self.api_client.list_subnets(network_id=network_id)
        subnets = subnet_response['subnets']
        for s in subnets:
            try:
                response.append(Subnet.from_dict(s))
            except Exception as e:
                LOG.info(_LI('ignoring subnet %s (%s) on network %s: %s'),
                         s.get('id'), s.get('cidr'),
                         network_id, e)
        return response

    def get_network_detail(self, network_id):
        network_response = self.api_client.show_network(network_id)['network']
        network = Network.from_dict(network_response)
        network.subnets = self.get_network_subnets(network_id)

        return network

    def get_ports_for_instance(self, instance_id):
        ports = self.api_client.list_ports(device_id=instance_id)['ports']

        mgt_port = None
        intf_ports = []

        for port in (Port.from_dict(p) for p in ports):
            if port.network_id == self.conf.management_network_id:
                mgt_port = port
            else:
                intf_ports.append(port)
        return mgt_port, intf_ports

    def create_management_port(self, object_id):
        return self.create_vrrp_port(
            object_id,
            self.conf.management_network_id,
            'MGT'
        )

    def create_vrrp_port(self, object_id, network_id, label='VRRP'):
        port_dict = dict(
            admin_state_up=True,
            network_id=network_id,
            name='ASTARA:%s:%s' % (label, object_id),
            security_groups=[]
        )

        if label in ['VRRP', 'LB']:
            port_dict['fixed_ips'] = []
            # disable port_securty on VRRP
            if self.conf.neutron_port_security_extension_enabled:
                port_dict['port_security_enabled'] = False

        response = self.api_client.create_port(dict(port=port_dict))
        port_data = response.get('port')
        if not port_data:
            raise ValueError(_(
                'Unable to create %s port for %s on network %s') %
                (label, object_id, network_id)
            )
        port = Port.from_dict(port_data)

        return port

    def delete_vrrp_port(self, object_id, label='VRRP'):
        name = 'ASTARA:%s:%s' % (label, object_id)
        response = self.api_client.list_ports(name=name)
        port_data = response.get('ports')

        if not port_data and self.conf.legacy_fallback_mode:
            name = name.replace('ASTARA', 'AKANDA')
            LOG.info(_LI('Attempting legacy query for %s.'), name)
            response = self.api_client.list_ports(name=name)
            port_data = response.get('ports')

        if not port_data:
            LOG.warning(_LW(
                'Unable to find VRRP port to delete with name %s.'), name)
        for port in port_data:
            self.api_client.delete_port(port['id'])

    def create_router_external_port(self, router):
        # FIXME: Need to make this smarter in case the switch is full.
        network_args = {'network_id': self.conf.external_network_id}
        update_args = {
            'name': router.name,
            'admin_state_up': router.admin_state_up,
            'external_gateway_info': network_args
        }

        self.api_client.update_router(
            router.id,
            body=dict(router=update_args)
        )
        new_port = self.get_router_external_port(router)

        # Make sure the port has enough IPs.
        subnets = self.get_network_subnets(self.conf.external_network_id)
        sn_by_id = {
            sn.id: sn
            for sn in subnets
        }
        sn_by_version = collections.defaultdict(list)
        for sn in subnets:
            sn_by_version[sn.ip_version].append(sn)
        versions_needed = set(sn_by_version.keys())
        found = set(sn_by_id[fip.subnet_id].ip_version
                    for fip in new_port.fixed_ips)
        if found != versions_needed:
            missing_versions = list(sorted(versions_needed - found))
            raise MissingIPAllocation(
                new_port.id,
                [(mv, [sn.id for sn in sn_by_version[mv]])
                 for mv in missing_versions]
            )
        return new_port

    def get_router_external_port(self, router):
        for i in six.moves.range(self.conf.max_retries):
            LOG.debug(
                'Looking for router external port. Attempt %d of %d',
                i,
                cfg.CONF.max_retries,
            )
            query_dict = {
                'device_owner': DEVICE_OWNER_ROUTER_GW,
                'device_id': router.id,
                'network_id': self.conf.external_network_id
            }
            ports = self.api_client.list_ports(**query_dict)['ports']

            if len(ports):
                port = Port.from_dict(ports[0])
                LOG.debug('Found router external port: %s', port.id)
                return port
            time.sleep(self.conf.retry_delay)
        raise RouterGatewayMissing()

    def _ensure_local_port(self, network_id, subnet_id, prefix,
                           network_type):
        driver = importutils.import_object(self.conf.interface_driver,
                                           self.conf)

        host_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()))

        name = 'ASTARA:RUG:%s' % network_type.upper()

        query_dict = dict(device_owner=DEVICE_OWNER_RUG,
                          device_id=host_id,
                          name=name,
                          network_id=network_id)

        ports = self.api_client.list_ports(**query_dict)['ports']

        if not ports and self.conf.legacy_fallback_mode:
            LOG.info(_LI('Attempting legacy query for %s.'), name)
            query_dict.update({
                'name': name.replace('ASTARA', 'AKANDA'),
                'device_owner': DEVICE_OWNER_RUG.replace('astara', 'akanda')
            })
            ports = self.api_client.list_ports(**query_dict)['ports']

        if ports and 'AKANDA' in ports[0]['name']:
            port = Port.from_dict(ports[0])
            LOG.info(
                _LI('migrating port to ASTARA for port %r and using local %s'),
                port,
                network_type
            )
            self.api_client.update_port(
                port.id,
                {
                    'port': {
                        'name': port.name.replace('AKANDA', 'ASTARA'),
                        'device_owner': DEVICE_OWNER_RUG
                    }
                }
            )
        elif ports:
            port = Port.from_dict(ports[0])
            LOG.info(_LI('already have local %s port, using %r'),
                     network_type, port)
        else:
            LOG.info(_LI('creating a new local %s port'), network_type)
            port_dict = {
                'admin_state_up': True,
                'network_id': network_id,
                'device_owner': DEVICE_OWNER_ROUTER_INT,  # lying here for IP
                'name': name,
                'device_id': host_id,
                'fixed_ips': [{
                    'subnet_id': subnet_id
                }],
                'binding:host_id': socket.gethostname()
            }
            port = Port.from_dict(
                self.api_client.create_port(dict(port=port_dict))['port'])

            # remove lie that enabled us pick IP on slaac subnet
            self.api_client.update_port(
                port.id,
                {'port': {'device_owner': DEVICE_OWNER_RUG}}
            )
            port.device_owner = DEVICE_OWNER_RUG

            LOG.info(_LI('new local %s port: %r'), network_type, port)

        # create the tap interface if it doesn't already exist
        if not ip_lib.device_exists(driver.get_device_name(port)):
            driver.plug(
                port.network_id,
                port.id,
                driver.get_device_name(port),
                port.mac_address)

            # add sleep to ensure that port is setup before use
            time.sleep(1)

        try:
            fixed_ip = [fip for fip in port.fixed_ips
                        if fip.subnet_id == subnet_id][0]
        except IndexError:
            raise MissingIPAllocation(port.id)

        ip_cidr = '%s/%s' % (fixed_ip.ip_address, prefix.split('/')[1])
        driver.init_l3(driver.get_device_name(port), [ip_cidr])
        return ip_cidr

    def ensure_local_external_port(self):
        return self._ensure_local_port(
            self.conf.external_network_id,
            self.conf.external_subnet_id,
            self.conf.external_prefix,
            'external')

    def ensure_local_service_port(self):
        return self._ensure_local_port(
            self.conf.management_network_id,
            self.conf.management_subnet_id,
            self.conf.management_prefix,
            'service')

    def purge_management_interface(self):
        driver = importutils.import_object(
            self.conf.interface_driver,
            self.conf
        )
        host_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()))
        query_dict = dict(
            device_owner=DEVICE_OWNER_RUG,
            name='ASTARA:RUG:MANAGEMENT',
            device_id=host_id
        )
        ports = self.api_client.list_ports(**query_dict)['ports']

        if not ports and self.conf.legacy_fallback_mode:
            query_dict.update({
                'name': 'AKANDA:RUG:MANAGEMENT',
                'device_owner': DEVICE_OWNER_RUG.replace('astara', 'akanda')
            })
            ports = self.api_client.list_ports(**query_dict)['ports']

        if ports:
            port = Port.from_dict(ports[0])
            device_name = driver.get_device_name(port)
            driver.unplug(device_name)

    def update_router_status(self, router_id, status):
        try:
            self.api_client.update_router_status(router_id, status)
        except Exception as e:
            # We don't want to die just because we can't tell neutron
            # what the status of the router should be. Log the error
            # but otherwise ignore it.
            LOG.info(_LI(
                'ignoring failure to update status for %s to %s: %s'),
                id, status, e,
            )

    def clear_device_id(self, port):
        self.api_client.update_port(port.id, {'port': {'device_id': ''}})
