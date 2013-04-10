import socket
import time
import uuid

import netaddr
from oslo.config import cfg
from quantumclient.v2_0 import client

from akanda.rug.openstack.common import importutils
from akanda.rug.openstack.common import context
from akanda.rug.openstack.common.rpc import proxy


# copied from Quantum source
DEVICE_OWNER_ROUTER_MGT = "network:router_management"
DEVICE_OWNER_ROUTER_INT = "network:router_interface"
DEVICE_OWNER_ROUTER_GW = "network:router_gateway"
DEVICE_OWNER_FLOATINGIP = "network:floatingip"
DEVICE_OWNER_RUG = "network:akanda"
PLUGIN_RPC_TOPIC = 'q-plugin'


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

        fips = [FloatingIP.from_dict(fip) for fip in d.get('floatingips')]

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
        retval = self.call(context.get_admin_context(),
                           self.make_msg('sync_routers', host=self.host,
                                         router_id=router_id),
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
        return Router.from_dict(
            self.rpc_client.get_routers(router_id=router_id)[0]
        )

    def get_router_for_tenant(self, tenant_id):
        routers = self.api_client.list_routers(tenant_id=tenant_id)['routers']

        if routers:
            return self.get_router_detail(routers[0]['id'])
        else:
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
        port = Port.from_dict(response['port'])
        args = dict(port_id=port.id, owner=DEVICE_OWNER_ROUTER_MGT)
        self.api_client.add_interface_router(router_id, args)

        return port

    def delete_router_management_port(self, router_id, port_id):
        args = dict(port_id=port_id, owner=DEVICE_OWNER_ROUTER_MGT)
        self.api_client.remove_interface_router(router_id, args)

    def create_router_external_port(self, router):
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
        return Router.from_dict(r['router']).external_port

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
        else:
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

            driver.plug(port.network_id,
                        port.id,
                        driver.get_device_name(port),
                        port.mac_address)
            # add sleep to ensure that port is setup before use
            time.sleep(1)

        driver.init_l3(driver.get_device_name(port), [ip_address])

        return port


def get_local_service_ip(conf):
    mgt_net = netaddr.IPNetwork(conf.management_prefix)
    rug_ip = '%s/%s' % (netaddr.IPAddress(mgt_net.first + 1),
                        mgt_net.prefixlen)
    return rug_ip
