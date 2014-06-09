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
from neutronclient.v2_0 import client

from akanda.rug.common.linux import ip_lib
from akanda.rug.openstack.common import importutils
from akanda.rug.openstack.common import context
from akanda.rug.openstack.common.rpc import proxy
from akanda.rug.openstack.common import log as logging

LOG = logging.getLogger(__name__)

# copied from Quantum source
DEVICE_OWNER_ROUTER_MGT = "network:router_management"
DEVICE_OWNER_ROUTER_INT = "network:router_interface"
DEVICE_OWNER_ROUTER_GW = "network:router_gateway"
DEVICE_OWNER_FLOATINGIP = "network:floatingip"
DEVICE_OWNER_RUG = "network:akanda"
PLUGIN_RPC_TOPIC = 'q-plugin'

STATUS_ACTIVE = 'ACTIVE'
STATUS_BUILD = 'BUILD'
STATUS_DOWN = 'DOWN'
STATUS_ERROR = 'ERROR'


class RouterGone(Exception):
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
    def __init__(self, id_, tenant_id, name, admin_state_up,
                 external_port=None, internal_ports=None,
                 management_port=None, floating_ips=None):
        self.id = id_
        self.tenant_id = tenant_id
        self.name = name
        self.admin_state_up = admin_state_up
        self.external_port = external_port
        self.management_port = management_port
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
        management_port = None
        internal_ports = []

        for port_dict in d['ports']:
            port = Port.from_dict(port_dict)
            if port.device_owner == DEVICE_OWNER_ROUTER_GW:
                external_port = port
            elif port.device_owner == DEVICE_OWNER_ROUTER_MGT:
                management_port = port
            elif port.device_owner == DEVICE_OWNER_ROUTER_INT:
                internal_ports.append(port)

        fips = [FloatingIP.from_dict(fip) for fip in d.get('_floatingips', [])]

        return cls(
            d['id'],
            d['tenant_id'],
            d['name'],
            d['admin_state_up'],
            external_port,
            internal_ports,
            management_port,
            floating_ips=fips
        )

    @property
    def ports(self):
        return itertools.chain(
            [self.management_port, self.external_port],
            self.internal_ports
        )


class Subnet(object):
    def __init__(self, id_, name, tenant_id, network_id, ip_version, cidr,
                 gateway_ip, enable_dhcp, dns_nameservers, host_routes):
        self.id = id_
        self.name = name
        self.tenant_id = tenant_id
        self.network_id = network_id
        self.ip_version = ip_version
        self.cidr = netaddr.IPNetwork(cidr)
        self.gateway_ip = netaddr.IPAddress(gateway_ip)
        self.enable_dhcp = enable_dhcp
        self.dns_nameservers = dns_nameservers
        self.host_routes = host_routes

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
            d['host_routes'])


class Port(object):
    def __init__(self, id_, device_id='', fixed_ips=None, mac_address='',
                 network_id='', device_owner=''):
        self.id = id_
        self.device_id = device_id
        self.fixed_ips = fixed_ips or []
        self.mac_address = mac_address
        self.network_id = network_id
        self.device_owner = device_owner

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
            device_owner=d['device_owner'])


class FixedIp(object):
    def __init__(self, subnet_id, ip_address):
        self.subnet_id = subnet_id
        self.ip_address = netaddr.IPAddress(ip_address)

    def __eq__(self, other):
        return type(self) == type(other) and vars(self) == vars(other)

    @classmethod
    def from_dict(cls, d):
        return cls(d['subnet_id'], d['ip_address'])


class AddressGroup(object):
    def __init__(self, id_, name, entries=None):
        self.id = id_
        self.name = name
        self.entries = entries or []

    @classmethod
    def from_dict(cls, d):
        return cls(
            d['id'],
            d['name'],
            [netaddr.IPNetwork(e['cidr']) for e in d['entries']])


class FilterRule(object):
    def __init__(self, id_, action, protocol, source, source_port,
                 destination, destination_port):
        self.id = id_
        self.action = action
        self.protocol = protocol
        self.source = source
        self.source_port = source_port
        self.destination = destination
        self.destination_port = destination_port

    @classmethod
    def from_dict(cls, d):
        if d['source']:
            source = AddressGroup.from_dict(d['source'])
        else:
            source = None

        if d['destination']:
            destination = AddressGroup.from_dict(d['destination'])
        else:
            destination = None

        return cls(
            d['id'],
            d['action'],
            d['protocol'],
            source,
            d['source_port'],
            destination,
            d['destination_port'])


class PortForward(object):
    def __init__(self, id_, name, protocol, public_port, private_port, port):
        self.id = id_
        self.name = name
        self.protocol = protocol
        self.public_port = public_port
        self.private_port = private_port
        self.port = port

    @classmethod
    def from_dict(cls, d):
        return cls(
            d['id'],
            d['name'],
            d['protocol'],
            d['public_port'],
            d['private_port'],
            Port.from_dict(d['port']))


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
    addressgroup_path = '/dhaddressgroup'
    addressentry_path = '/dhaddressentry'
    filterrule_path = '/dhfilterrule'
    portalias_path = '/dhportalias'
    portforward_path = '/dhportforward'
    routerstatus_path = '/dhrouterstatus'

    # portalias crud
    @client.APIParamsCall
    def list_portalias(self, **params):
        return self.get(self.portalias_path, params=params)

    @client.APIParamsCall
    def show_portalias(self, portforward, **params):
        return self.get('%s/%s' % (self.portalias_path, portforward),
                        params=params)

    # portforward crud
    @client.APIParamsCall
    def list_portforwards(self, **params):
        return self.get(self.portforward_path, params=params)

    @client.APIParamsCall
    def show_portforward(self, portforward, **params):
        return self.get('%s/%s' % (self.portforward_path, portforward),
                        params=params)

    # filterrule crud
    @client.APIParamsCall
    def list_filterrules(self, **params):
        return self.get(self.filterrule_path, params=params)

    @client.APIParamsCall
    def show_filterrule(self, filterrule, **params):
        return self.get('%s/%s' % (self.filterrule_path, filterrule),
                        params=params)

    # address group crud
    @client.APIParamsCall
    def list_addressgroups(self, **params):
        return self.get(self.addressgroup_path, params=params)

    @client.APIParamsCall
    def show_addressgroup(self, addressgroup, **params):
        return self.get('%s/%s' % (self.addressgroup_path,
                                   addressgroup),
                        params=params)

    # addressentries crud
    @client.APIParamsCall
    def list_addressentries(self, **params):
        return self.get(self.addressentry_path, params=params)

    @client.APIParamsCall
    def show_addressentry(self, addressentry, **params):
        return self.get('%s/%s' % (self.addressentry_path,
                                   addressentry),
                        params=params)

    @client.APIParamsCall
    def update_router_status(self, router, status):
        return self.put(
            '%s/%s' % (self.routerstatus_path, router),
            body={'routerstatus': {'status': status}}
        )


class L3PluginApi(proxy.RpcProxy):
    """Agent side of the Qunatum l3 agent RPC API."""

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic, host):
        super(L3PluginApi, self).__init__(
            topic=topic, default_version=self.BASE_RPC_API_VERSION)
        self.host = host

    def get_routers(self, router_id=None):
        """Make a remote process call to retrieve the sync data for routers."""
        router_id = [router_id] if router_id else None
        # yes the plural is intended for havana compliance
        retval = self.call(context.get_admin_context(),
                           self.make_msg('sync_routers', host=self.host,
                                         router_ids=router_id),  # plural
                           topic=self.topic)
        return retval


class Quantum(object):
    def __init__(self, conf):
        self.conf = conf
        self.api_client = AkandaExtClientWrapper(
            username=conf.admin_user,
            password=conf.admin_password,
            tenant_name=conf.admin_tenant_name,
            auth_url=conf.auth_url,
            auth_strategy=conf.auth_strategy,
            auth_region=conf.auth_region
        )
        self.rpc_client = L3PluginApi(PLUGIN_RPC_TOPIC, cfg.CONF.host)

    def get_routers(self):
        """Return a list of routers."""
        return [Router.from_dict(r) for r in
                self.rpc_client.get_routers()]

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
        return [Subnet.from_dict(s) for s in
                self.api_client.list_subnets(network_id=network_id)['subnets']]

    def get_addressgroups(self, tenant_id):
        return [AddressGroup.from_dict(g) for g in
                self.api_client.list_addressgroups(
                    tenant_id=tenant_id)['addressgroups']]

    def get_filterrules(self, tenant_id):
        return [FilterRule.from_dict(r) for r in
                self.api_client.list_filterrules(
                    tenant_id=tenant_id)['filterrules']]

    def get_portforwards(self, tenant_id):
        return [PortForward.from_dict(f) for f in
                self.api_client.list_portforwards(
                    tenant_id=tenant_id)['portforwards']]

    def create_router_management_port(self, router_id):
        port_dict = dict(admin_state_up=True,
                         network_id=self.conf.management_network_id,
                         device_owner=DEVICE_OWNER_ROUTER_MGT
                         )
        response = self.api_client.create_port(dict(port=port_dict))
        port_data = response.get('port')
        if not port_data:
            raise ValueError('No port data found for router %s network %s' %
                             (router_id, self.conf.management_network_id))
        port = Port.from_dict(port_data)
        args = dict(port_id=port.id, owner=DEVICE_OWNER_ROUTER_MGT)
        self.api_client.add_interface_router(router_id, args)

        return port

    def delete_router_management_port(self, router_id, port_id):
        args = dict(port_id=port_id, owner=DEVICE_OWNER_ROUTER_MGT)
        self.api_client.remove_interface_router(router_id, args)

    def create_router_external_port(self, router):
        # FIXME: Need to make this smarter in case the switch is full.
        network_args = {'network_id': self.conf.external_network_id}
        update_args = {
            'name': router.name,
            'admin_state_up': router.admin_state_up,
            'external_gateway_info': network_args
        }

        r = self.api_client.update_router(
            router.id,
            body=dict(router=update_args)
        )
        new_port = Router.from_dict(r['router']).external_port

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

    def ensure_local_service_port(self):
        driver = importutils.import_object(self.conf.interface_driver,
                                           self.conf)

        host_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()))

        query_dict = dict(device_owner=DEVICE_OWNER_RUG,
                          device_id=host_id)

        ports = self.api_client.list_ports(**query_dict)['ports']

        ip_address = get_local_service_ip(self.conf)

        if ports:
            port = Port.from_dict(ports[0])
            LOG.info('already have local service port, using %r', port)
        else:
            LOG.info('creating a new local service port')
            # create the missing local port
            port_dict = dict(
                admin_state_up=True,
                network_id=self.conf.management_network_id,
                device_owner=DEVICE_OWNER_RUG,
                device_id=host_id,
                fixed_ips=[{
                    'ip_address': ip_address.split('/')[0],
                    'subnet_id': self.conf.management_subnet_id
                }]
            )

            port = Port.from_dict(
                self.api_client.create_port(dict(port=port_dict))['port'])
            LOG.info('new local service port: %r', port)

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

    def purge_management_interface(self):
        driver = importutils.import_object(
            self.conf.interface_driver,
            self.conf
        )
        host_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()))
        query_dict = dict(device_owner=DEVICE_OWNER_RUG, device_id=host_id)
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
