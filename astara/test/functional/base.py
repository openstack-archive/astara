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

import ConfigParser
import netaddr
import os
import subprocess
import testtools
import time

from oslo_config import cfg

from astara.api import astara_client

from keystoneclient.v2_0 import client as _keystoneclient
from neutronclient.v2_0 import client as _neutronclient
from novaclient import client as _novaclient

from keystoneclient import exceptions as ksc_exceptions
from neutronclient.common import exceptions as neutron_exceptions

from tempest_lib.common.utils import data_utils

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), 'test.conf')
DEFAULT_ACTIVE_TIMEOUT = 340

from astara.test.functional import config
config.register_opts()
CONF = cfg.CONF


def parse_config():
    config_file = os.environ.get('AKANDA_TEST_CONFIG',
                                 DEFAULT_CONFIG)
    cfg.CONF(
        [], project='astara-orchestrator-functional',
        default_config_files=[config_file])


class ClientManager(object):
    """A client manager using specified credentials"""
    def __init__(self, username, password, tenant_name, auth_url):
        parse_config()
        self.username = username
        self.password = password
        self.tenant_name = tenant_name
        self.auth_url = auth_url

        self._keystoneclient = None
        self._neutronclient = None
        self._novaclient = None

    @property
    def novaclient(self):
        if not self._novaclient:
            self._novaclient = _novaclient.Client(
                version=2,
                username=self.username,
                api_key=self.password,
                project_id=self.tenant_name,
                auth_url=self.auth_url,
                auth_system='keystone',
                auth_plugin='password',
            )
        return self._novaclient

    @property
    def neutronclient(self):
        if not self._neutronclient:
            self._neutronclient = _neutronclient.Client(
                username=self.username,
                password=self.password,
                tenant_name=self.tenant_name,
                auth_url=self.auth_url,
                auth_system='keystone',
            )
        return self._neutronclient

    @property
    def keystoneclient(self):
        if not self._keystoneclient:
            self._keystoneclient = _keystoneclient.Client(
                username=self.username,
                password=self.password,
                tenant_name=self.tenant_name,
                auth_url=self.auth_url
            )
        return self._keystoneclient

    @property
    def tenant_id(self):
        return self.keystoneclient.tenant_id


class AdminClientManager(ClientManager):
    """A client manager using credentials loaded from test.conf, which
    are assumed to be admin.
    """
    def __init__(self):
        parse_config()
        super(AdminClientManager, self).__init__(
            username=CONF.os_username,
            password=CONF.os_password,
            tenant_name=CONF.os_tenant_name,
            auth_url=CONF.os_auth_url,
        )


class TestTenant(object):
    def __init__(self):
        parse_config()
        self.username = data_utils.rand_name(name='user', prefix='akanda')
        self.user_id = None
        self.password = data_utils.rand_password()
        self.tenant_name = data_utils.rand_name(name='tenant', prefix='akanda')
        self.tenant_id = None

        admin_ks_client = AdminClientManager().keystoneclient
        self.auth_url = admin_ks_client.auth_url
        self._admin_ks_client = admin_ks_client

        # create the tenant before creating its clients.
        self._create_tenant()

        self.clients = ClientManager(self.username, self.password,
                                     self.tenant_name, self.auth_url)

        self._subnets = []
        self._routers = []

    def _create_tenant(self):
        tenant = self._admin_ks_client.tenants.create(self.tenant_name)
        self.tenant_id = tenant.id
        user = self._admin_ks_client.users.create(name=self.username,
                                                  password=self.password,
                                                  tenant_id=self.tenant_id)
        self.user_id = user.id

    def setup_networking(self):
        """"Create a network + subnet for the tenant.  Also creates a router
        if required, and attaches the subnet to it.

        :returns: a (network dict, router dict) tuple
        """
        # NOTE(adam_g): I didn't expect simply creating a network
        # to also create a subnet and router automatically, but this
        # does?
        net_body = {
            'network': {
                'name': data_utils.rand_name(name='network', prefix='ak'),
                'admin_state_up': False,
                'tenant_id': self.tenant_id
            }}
        network = self.clients.neutronclient.create_network(net_body)
        network = network.get('network')
        if not network:
            raise Exception('Failed to create default tenant network')

        if not CONF.astara_auto_add_resources:
            addr = netaddr.IPNetwork(CONF.test_subnet_cidr)
            subnet_body = {
                'subnet': {
                    'name': data_utils.rand_name(name='subnet', prefix='ak'),
                    'network_id': network['id'],
                    'cidr': CONF.test_subnet_cidr,
                    'ip_version': addr.version,
                }
            }
            subnet = self.clients.neutronclient.create_subnet(
                body=subnet_body)['subnet']
            router_body = {
                'router': {
                    'name': data_utils.rand_name(name='router', prefix='ak'),
                    'admin_state_up': True,
                    'tenant_id': self.tenant_id,
                }
            }
            router = self.clients.neutronclient.create_router(
                body=router_body)['router']
            self.clients.neutronclient.add_interface_router(
                router['id'], {'subnet_id': subnet['id']}
            )
        else:
            # routers report as ACTIVE initially (LP: #1491673)
            time.sleep(2)
            i = 0
            while True:
                routers = self.clients.neutronclient.list_routers()
                routers = routers.get('routers')
                if routers:
                    router = routers[0]
                    break
                if i >= CONF.appliance_active_timeout:
                    raise Exception('Timed out waiting for default router.')
                time.sleep(1)
            i += 1

        # routers report as ACTIVE initially (LP: #1491673)
        time.sleep(2)
        return network, router

    def cleanup_neutron(self):
        """Clean tenant environment of neutron resources"""
        router_interface_ports = [
            p for p in self.clients.neutronclient.list_ports()['ports']
            if 'router_interface' in p['device_owner']]
        for rip in router_interface_ports:
            self.clients.neutronclient.remove_interface_router(
                rip['device_id'],
                body=dict(port_id=router_interface_ports[0]['id']))

        [self.clients.neutronclient.delete_router(r['id'])
         for r in self.clients.neutronclient.list_routers()['routers']]

        time.sleep(2)

        for port in self.clients.neutronclient.list_ports().get('ports'):
            try:
                self.clients.neutronclient.delete_port(port['id'])
            except neutron_exceptions.PortNotFoundClient:
                pass

        for subnet in self.clients.neutronclient.list_subnets().get('subnets'):
            try:
                self.clients.neutronclient.delete_subnet(subnet['id'])
            except neutron_exceptions.NotFound:
                pass

        tenant_nets = [
            n for n in
            self.clients.neutronclient.list_networks().get('networks')
            if n['tenant_id'] == self.tenant_id]
        for net in tenant_nets:
            try:
                self.clients.neutronclient.delete_network(net['id'])
            except neutron_exceptions.NetworkNotFoundClient:
                pass

    def cleanUp(self):
        self.cleanup_neutron()

        self._admin_ks_client.users.delete(self.user_id)
        self._admin_ks_client.tenants.delete(self.tenant_id)


class AstaraFunctionalBase(testtools.TestCase):
    _test_tenants = []

    def setUp(self):
        super(AstaraFunctionalBase, self).setUp()

        self.ak_client = astara_client

        self.novaclient = _novaclient.Client(
            version=2,
            username=CONF.os_username,
            api_key=CONF.os_password,
            project_id=CONF.os_tenant_name,
            auth_url=CONF.os_auth_url,
            auth_system='keystone',
            auth_plugin='password',
        )
        self.admin_clients = AdminClientManager()

        self._management_address = None

    @classmethod
    def setUpClass(cls):
        cls._test_tenants = []

    @classmethod
    def tearDownClass(cls):
        try:
            [t.cleanUp() for t in cls._test_tenants]
        except ksc_exceptions.NotFound:
            pass

    @classmethod
    def get_tenant(cls):
        """Creates a new test tenant

        This tenant is assumed to be empty of any cloud resources
        and will be destroyed on test class teardown.
        """
        tenant = TestTenant()
        cls._test_tenants.append(tenant)
        return tenant

    def get_router_appliance_server(self, router_uuid, retries=0,
                                    wait_for_active=False):
        """Returns a Nova server object for router"""
        i = 0
        while True:
            service_instance = \
                [instance for instance in
                 self.admin_clients.novaclient.servers.list(
                     search_opts={
                         'all_tenants': 1,
                         'tenant_id': CONF.service_tenant_id}
                 ) if router_uuid in instance.name]

            if service_instance:
                service_instance = service_instance[0]
                break

            if not service_instance:
                if i < retries:
                    i += 1
                    time.sleep(1)
                    continue
                raise Exception(
                    'Could not get nova server for router %s' % router_uuid)

        if wait_for_active:
            i = 0
            while i <= CONF.appliance_active_timeout:
                service_instance = self.admin_clients.novaclient.servers.get(
                    service_instance.id)
                if service_instance.status == 'ACTIVE':
                    return service_instance
                else:
                    i += 1
                    time.sleep(1)
        else:
            return service_instance

    def get_management_address(self, router_uuid):
        if self._management_address:
            return self._management_address['addr']

        service_instance = self.get_router_appliance_server(router_uuid)

        try:
            self._management_address = service_instance.addresses['mgt'][0]
        except KeyError:
            self.fail('"mgt" port not found on service instance %s (%s)' %
                      (service_instance.id, service_instance.name))
        return self._management_address['addr']

    def assert_router_is_active(self, router_uuid=None):
        if not router_uuid:
            router_uuid = CONF.astara_test_router_uuid
        i = 0
        res = self.admin_clients.neutronclient.show_router(router_uuid)
        router = res['router']
        while router['status'] != 'ACTIVE':
            if i >= CONF.appliance_active_timeout:
                raise Exception(
                    'Timed out waiting for router %s to become ACTIVE, '
                    'current status=%s' % (router_uuid, router['status']))
            time.sleep(1)
            res = self.admin_clients.neutronclient.show_router(router_uuid)
            router = res['router']
            i += 1

    def ping_router_mgt_address(self, router_uuid):
        server = self.get_router_appliance_server(router_uuid)
        mgt_interface = server.addresses['mgt'][0]
        program = {4: 'ping', 6: 'ping6'}
        cmd = [program[mgt_interface['version']], '-c5', mgt_interface['addr']]
        try:
            subprocess.check_call(cmd)
        except:
            raise Exception('Failed to ping router with command: %s' % cmd)
