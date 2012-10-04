import socket
import uuid

import netaddr
from quantumclient.v2_0 import client

from akanda.rug.openstack.common import importutils


# copied from Quantum source
DEVICE_OWNER_ROUTER_MGT = "network:router_management"
DEVICE_OWNER_ROUTER_INT = "network:router_interface"
DEVICE_OWNER_ROUTER_GW = "network:router_gateway"
DEVICE_OWNER_FLOATINGIP = "network:floatingip"

DEVICE_OWNER_RUG = "akanda:rug"


class Router(object):
    def __init__(self, id_, tenant_id, name, external_port=None,
                 internal_ports=None, management_port=None):
        self.id = id_
        self.tenant_id = tenant_id
        self.name = name
        self.external_port = external_port
        self.management_port = management_port
        self.internal_ports = internal_ports or []

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
        rtr = cls( d['id'], d['tenant_id'], d['name'], d.get('external_port'))

        for port_dict in d['ports']:
            port = Port.from_dict(port_dict)
            if port.device_owner == DEVICE_OWNER_ROUTER_GW:
                rtr.external_port = port
            elif port.device_owner == DEVICE_OWNER_ROUTER_MGT:
                rtr.management_port = port
            elif port.device_owner == DEVICE_OWNER_ROUTER_INT:
                rtr.internal_ports.append(port)

        return rtr


class Port(object):
    def __init__(self, id_, device_id='', fixed_ips=[], mac_address='',
                 network_id='', device_owner=''):
        self.id = id_
        self.device_id = device_id
        self.fixed_ips = fixed_ips
        self.mac_address = mac_address
        self.network_id = network_id
        self.device_owner = device_owner

    def __eq__(self, other):
        return type(self) == type(other) and vars(self) == vars(other)

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
        self.ip_address = netaddr.IPNetwork(ip_address)

    def __eq__(self, other):
        return type(self) == type(other) and vars(self) == vars(other)

    @classmethod
    def from_dict(cls, d):
        return cls(d['subnet_id'], d['ip_address'])


class Network(object):
    def __init__(self):
        pass


class Quantum(object):
    def __init__(self, conf):
        self.conf = conf
        self.client = client.Client(
            username=conf.admin_user,
            password=conf.admin_password,
            tenant_name=conf.admin_tenant_name,
            auth_url=conf.auth_url,
            auth_strategy=conf.auth_strategy,
            auth_region=conf.auth_region)

    def get_routers(self):
        """Return a list of routers."""
        retval = {}

        # To reduce HTTP requests, get a list of routers and then get a list
        # of router ports to merge the results in code.
        for r in self.client.list_routers()['routers']:
            rtr = Router.from_dict(r)
            retval[r['id']] = rtr
        return retval

    def get_router_detail(self, router_id):
        """Return detailed information about a router and it's networks."""
        return Router.from_dict(self.client.show_router(router_id)['router'])

    def get_network_list(self):
        return [n.id for n in self.client.list_networks()['networks']]

    def create_router_management_port(self, router_id):
        port_dict = dict(admin_state_up=True,
                         network_id=self.conf.management_network_id,
                         device_owner=DEVICE_OWNER_ROUTER_MGT
                         )
        port = Port.from_dict(
            self.client.create_port(dict(port=port_dict))['port'])
        args = dict(port_id=port.id, owner=DEVICE_OWNER_ROUTER_MGT)
        self.client.add_interface_router(router_id, args)

        return port

    def delete_router_management_port(self, router_id, port_id):
        args = dict(port_id=port_id, owner=DEVICE_OWNER_ROUTER_MGT)
        self.client.remove_interface_router(router_id, args)

    def ensure_local_service_port(self):
        driver = importutils.import_object(self.conf.interface_driver,
                                           self.conf)

        host_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()))

        query_dict = dict(device_owner=DEVICE_OWNER_RUG,
                         device_id=host_id)

        ports = self.client.list_ports(**query_dict)['ports']

        if ports:
            port = Port.from_dict(ports[0])
        else:
            # create the missing local port
            port_dict = dict(admin_state_up=True,
                             network_id=self.conf.management_network_id,
                             device_owner=DEVICE_OWNER_RUG,
                             device_id=host_id)

            port = Port.from_dict(
                self.client.create_port(dict(port=port_dict))['port'])


            driver.plug(port.network_id,
                        port.id,
                        driver.get_device_name(port),
                        port.mac_address)

        mgt_net = netaddr.IPNetwork(self.conf.management_prefix)
        rug_ip = '%s/%s' % (netaddr.IPAddress(mgt_net.first+1),
                            mgt_net.prefixlen)

        driver.init_l3(driver.get_device_name(port), [rug_ip])

        return port
