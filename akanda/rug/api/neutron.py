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
from oslo.config import cfg
from oslo_context import context
from oslo_messaging.rpc.client import RPCClient
from neutronclient.v2_0 import client

from akanda.rug.common.linux import ip_lib
from akanda.rug.openstack.common import importutils
from akanda.rug.common import log_shim as logging
from akanda.rug.common import rpc

LOG = logging.getLogger(__name__)

# copied from Neutron source
DEVICE_OWNER_ROUTER_MGT = "network:router_management"
DEVICE_OWNER_ROUTER_INT = "network:router_interface"
DEVICE_OWNER_ROUTER_GW = "network:router_gateway"
DEVICE_OWNER_FLOATINGIP = "network:floatingip"
DEVICE_OWNER_RUG = "network:akanda"
PLUGIN_RPC_TOPIC = 'q-l3-plugin'

STATUS_ACTIVE = 'ACTIVE'
STATUS_BUILD = 'BUILD'
STATUS_DOWN = 'DOWN'
STATUS_ERROR = 'ERROR'


class RouterGone(Exception):
    pass


class RouterGatewayMissing(Exception):
    pass


class MissingIPAllocation(Exception):

    def __init__(self, port_id, missing):
        self.port_id = port_id
        self.missing = missing
        msg = 'Port %s missing an expected ' % port_id
        ip_msg = ' and '.join(
            ('IPv%s address from one of %s' %
             (mv, missing_subnets))
            for mv, missing_subnets in missing
        )
        super(MissingIPAllocation, self).__init__(msg + ip_msg)


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
            floating_ips=fips
        )

    @property
    def ports(self):
        return itertools.chain(
            [self.external_port],
            self.internal_ports
        )


class Subnet(object):
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
                'Invalid CIDR %r for subnet %s of network %s: %s' % (
                    cidr, id_, network_id, e,
                )
            )
        try:
            self.gateway_ip = netaddr.IPAddress(gateway_ip)
        except (TypeError, netaddr.AddrFormatError) as e:
            self.gateway_ip = None
            LOG.info('Bad gateway_ip on subnet %s: %r (%s)',
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


class Port(object):
    def __init__(self, id_, device_id='', fixed_ips=None, mac_address='',
                 network_id='', device_owner='', name=''):
        self.id = id_
        self.device_id = device_id
        self.fixed_ips = fixed_ips or []
        self.mac_address = mac_address
        self.network_id = network_id
        self.device_owner = device_owner
        self.name = name

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
            name=d['name'])


class FixedIp(object):
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


class AkandaExtClientWrapper(client.Client):
    """Add client support for Akanda Extensions. """

    routerstatus_path = '/dhrouterstatus'

    @client.APIParamsCall
    def update_router_status(self, router, status):
        return self.put(
            '%s/%s' % (self.routerstatus_path, router),
            body={'routerstatus': {'status': status}}
        )


class L3PluginApi(object):

    """Agent side of the Qunatum l3 agent RPC API."""

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic, host):
        self.host = host
        self._client = rpc.get_rpc_client(
            topic=topic,
            exchange=cfg.CONF.neutron_control_exchange,
            version = self.BASE_RPC_API_VERSION,
        )

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
        self.api_client = AkandaExtClientWrapper(
            username=conf.admin_user,
            password=conf.admin_password,
            tenant_name=conf.admin_tenant_name,
            auth_url=conf.auth_url,
            auth_strategy=conf.auth_strategy,
            region_name=conf.auth_region
        )
        self.rpc_client = L3PluginApi(PLUGIN_RPC_TOPIC, cfg.CONF.host)

    def get_routers(self, detailed=True):
        """Return a list of routers."""
        if detailed:
            return [Router.from_dict(r) for r in
                    self.rpc_client.get_routers()]
        routers = self.api_client.list_routers().get('routers', [])
        return [Router.from_dict(r) for r in routers]

    def get_router_detail(self, router_id):
        """Return detailed information about a router and it's networks."""
        router = self.rpc_client.get_routers(router_id=router_id)
        try:
            return Router.from_dict(router[0])
        except IndexError:
            raise RouterGone('the router is no longer available')

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
                LOG.info('ignoring subnet %s (%s) on network %s: %s',
                         s.get('id'), s.get('cidr'),
                         network_id, e)
        return response

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
            name='AKANDA:%s:%s' % (label, object_id),
            security_groups=[]
        )

        if label == 'VRRP':
            port_dict['fixed_ips'] = []

        response = self.api_client.create_port(dict(port=port_dict))
        port_data = response.get('port')
        if not port_data:
            raise ValueError(
                'Unable to create %s port for %s on network %s' %
                (label, object_id, network_id)
            )
        port = Port.from_dict(port_data)

        return port

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
        for i in xrange(self.conf.max_retries):
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
                LOG.debug('Found router external port: %s' % port.id)
                return port
            time.sleep(self.conf.retry_delay)
        raise RouterGatewayMissing()

    def _ensure_local_port(self, network_id, subnet_id,
                           network_type, ip_address):
        driver = importutils.import_object(self.conf.interface_driver,
                                           self.conf)

        host_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()))

        name = 'AKANDA:RUG:%s' % network_type.upper()

        query_dict = dict(device_owner=DEVICE_OWNER_RUG,
                          device_id=host_id,
                          name=name,
                          network_id=network_id)

        ports = self.api_client.list_ports(**query_dict)['ports']

        if ports:
            port = Port.from_dict(ports[0])
            LOG.info('already have local %s port, using %r',
                     network_type, port)
        else:
            LOG.info('creating a new local %s port', network_type)
            port_dict = {
                'admin_state_up': True,
                'network_id': network_id,
                'device_owner': DEVICE_OWNER_ROUTER_INT,  # lying here for IP
                'name': name,
                'device_id': host_id,
                'fixed_ips': [{
                    'ip_address': ip_address.split('/')[0],
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

            LOG.info('new local %s port: %r', network_type, port)

        # create the tap interface if it doesn't already exist
        if not ip_lib.device_exists(driver.get_device_name(port)):
            driver.plug(
                port.network_id,
                port.id,
                driver.get_device_name(port),
                port.mac_address)

            # add sleep to ensure that port is setup before use
            time.sleep(1)

        driver.init_l3(driver.get_device_name(port), [ip_address])
        return port

    def ensure_local_external_port(self):
        return self._ensure_local_port(
            self.conf.external_network_id,
            self.conf.external_subnet_id,
            'external',
            get_local_external_ip(self.conf)
        )

    def ensure_local_service_port(self):
        return self._ensure_local_port(
            self.conf.management_network_id,
            self.conf.management_subnet_id,
            'service',
            get_local_service_ip(self.conf)
        )

    def purge_management_interface(self):
        driver = importutils.import_object(
            self.conf.interface_driver,
            self.conf
        )
        host_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()))
        query_dict = dict(
            device_owner=DEVICE_OWNER_RUG,
            name='AKANDA:RUG:MANAGEMENT',
            device_id=host_id
        )
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
            LOG.info(
                'ignoring failure to update status for router %s to %s: %s',
                router_id, status, e,
            )

    def clear_device_id(self, port):
        self.api_client.update_port(port.id, {'port': {'device_id': ''}})


def get_local_service_ip(conf):
    mgt_net = netaddr.IPNetwork(conf.management_prefix)
    rug_ip = '%s/%s' % (netaddr.IPAddress(mgt_net.first + 1),
                        mgt_net.prefixlen)
    return rug_ip


def get_local_external_ip(conf):
    external_net = netaddr.IPNetwork(conf.external_prefix)
    external_ip = '%s/%s' % (netaddr.IPAddress(external_net.first + 1),
                             external_net.prefixlen)
    return external_ip
