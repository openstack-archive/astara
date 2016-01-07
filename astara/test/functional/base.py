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

import netaddr
import os
import subprocess
import testtools
import time

from oslo_config import cfg
from oslo_log import log as logging

from astara.api import astara_client

from keystoneclient.v2_0 import client as _keystoneclient
from neutronclient.v2_0 import client as _neutronclient
from novaclient import client as _novaclient

from keystoneclient import exceptions as ksc_exceptions
from neutronclient.common import exceptions as neutron_exceptions

from tempest_lib.common.utils import data_utils
from tempest_lib import exceptions as tempest_exc
from tempest_lib.common import ssh

from astara.test.functional import config

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), 'test.conf')

DEFAULT_ACTIVE_TIMEOUT = 340

SSH_USERNAME = 'astara'
SSH_TIMEOUT = 340

config.register_opts()
CONF = cfg.CONF
logging.register_options(CONF)

LOG = None


def parse_config():
    config_file = os.environ.get('AKANDA_TEST_CONFIG',
                                 DEFAULT_CONFIG)
    cfg.CONF(
        [], project='astara-orchestrator-functional',
        default_config_files=[config_file])
    logging.set_defaults(default_log_levels=[
        'neutronclient=WARN',
        'keystoneclient=WARN',
    ])
    logging.setup(CONF, 'astara_functional')
    global LOG
    LOG = logging.getLogger(__name__)


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

    def get_router_appliance_server(self, resource, uuid, retries=10,
                                    wait_for_active=False):
        """Returns a Nova server object for router"""
        i = 0
        LOG.debug(
            'Looking for nova backing instance for %s %s',
            resource, uuid)

        while True:
            service_instance = \
                [instance for instance in
                 self.novaclient.servers.list(
                     search_opts={
                         'all_tenants': 1,
                         'tenant_id': CONF.service_tenant_id}
                 ) if instance.name == 'ak-%s-%s' % (resource, uuid)]

            if service_instance:
                service_instance = service_instance[0]
                LOG.debug(
                    'Found backing instance for %s %s: %s',
                    resource, uuid, service_instance)
                break

            if not service_instance:
                if i < retries:
                    i += 1
                    time.sleep(1)
                    LOG.debug('Backing instance not found, will retry %s/%s',
                              i, retries)
                    continue
                raise Exception(
                    'Could not get nova server for %s %s' %
                    (resource, id))

        if wait_for_active:
            LOG.debug('Waiting for backing instance %s to become ACTIVE',
                      service_instance)
            i = 0
            while i <= CONF.appliance_active_timeout:
                service_instance = self.novaclient.servers.get(
                    service_instance.id)
                if service_instance.status == 'ACTIVE':
                    LOG.debug('Instance %s status==ACTIVE', service_instance)
                    return service_instance
                else:
                    LOG.debug('Instance %s status==%s, will wait',
                              service_instance, service_instance.status)
                    i += 1
                    time.sleep(1)
        else:
            return service_instance


class TestTenant(object):
    def __init__(self):
        parse_config()
        self.username = data_utils.rand_name(name='user', prefix='akanda')
        self.user_id = None
        self.password = data_utils.rand_password()
        self.tenant_name = data_utils.rand_name(name='tenant', prefix='akanda')
        self.tenant_id = None

        self._admin_clients = AdminClientManager()
        self._admin_ks_client = self._admin_clients.keystoneclient
        self.auth_url = self._admin_ks_client.auth_url

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
        LOG.debug('Created new test tenant: %s (%s)',
                  self.tenant_id, self.user_id)

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
        LOG.debug('Creating network: %s', net_body)
        network = self.clients.neutronclient.create_network(net_body)
        network = network.get('network')
        if not network:
            raise Exception('Failed to create default tenant network')
        LOG.debug('Created network: %s', network)

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
            LOG.debug('Creating subnet: %s', subnet_body)
            subnet = self.clients.neutronclient.create_subnet(
                body=subnet_body)['subnet']
            LOG.debug('Created subnet: %s', subnet)
            router_body = {
                'router': {
                    'name': data_utils.rand_name(name='router', prefix='ak'),
                    'admin_state_up': True,
                    'tenant_id': self.tenant_id,
                }
            }
            LOG.debug('Creating router: %s', router_body)
            router = self.clients.neutronclient.create_router(
                body=router_body)['router']
            LOG.debug('Created router: %s', router)

            LOG.debug(
                'Attaching interface on subnet %s to router %s',
                subnet['id'], router['id'])
            self.clients.neutronclient.add_interface_router(
                router['id'], {'subnet_id': subnet['id']}
            )
            LOG.debug(
                'Attached interface on subnet %s to router %s',
                subnet['id'], router['id'])

        else:
            # routers report as ACTIVE initially (LP: #1491673)
            time.sleep(2)
            i = 0
            LOG.debug('Waiting for astara auto-created router')
            while True:
                routers = self.clients.neutronclient.list_routers()
                routers = routers.get('routers')
                if routers:
                    router = routers[0]
                    LOG.debug('Found astara auto-created router: %s', router)
                    break
                if i >= CONF.appliance_active_timeout:
                    raise Exception('Timed out waiting for default router.')
                time.sleep(1)
            i += 1

        # routers report as ACTIVE initially (LP: #1491673)
        time.sleep(2)
        return network, router

    def _wait_for_backing_instance_delete(self, resource_ids):
        attempt = 0
        max_attempts = 10
        for rid in resource_ids:
            LOG.debug(
                'Waiting on deletion of backing instance for resource %s', rid)
            while True:
                try:
                    self.admin_clients.get_router_appliance_server(
                        'router', rid)
                    LOG.debug(
                        'Still waiting for deletion of backing instance for %s'
                        ' , will wait (%s/%s)' % rid, attempt, max_attempts)
                    if attempt == max_attempts:
                        m = ('Timed out waiting on deletion of backing '
                             'instance for %s after %s sec.' %
                             (rid, max_attempts))
                        LOG.debug(m)
                        self.fail(m)
                    max_attempts += 1
                    time.sleep(1)
                except Exception:
                    LOG.debug('Backing instance for resource %s deleted')
                    break

    def _wait_for_neutron_delete(self, thing, ids):
        show = getattr(self.clients.neutronclient, 'show_' + thing)
        attempt = 0
        max_attempts = 10
        for i in ids:
            LOG.debug('Waiting for deletion of %s %s', thing, i)
            while True:
                try:
                    show(i)
                except neutron_exceptions.NeutronClientException as e:
                    if e.status_code == 404:
                        LOG.debug('Deletion of %s %s complete', thing, i)
                        break
                if attempt == max_attempts:
                    self.fail(
                        'Timed out waiting for deletion of %s %s after %s sec.'
                        % (thing, i, max_attempts))
                LOG.debug(
                    'Still waiting for deletion of %s %s, will wait (%s/%s)',
                    thing, i, attempt, max_attempts)
                attempt += 1
                time.sleep(1)

        # also wait for nova backing instance to delete after routers
        if thing in 'router':
            self._wait_for_backing_instance_delete(ids)

    def cleanup_neutron(self):
        """Clean tenant environment of neutron resources"""
        LOG.debug('Cleaning up created neutron resources')
        router_interface_ports = [
            p for p in self.clients.neutronclient.list_ports()['ports']
            if 'router_interface' in p['device_owner']]
        for rip in router_interface_ports:
            LOG.debug('Deleting router interface port: %s', rip)
            self.clients.neutronclient.remove_interface_router(
                rip['device_id'],
                body=dict(port_id=router_interface_ports[0]['id']))

        astara_router_ports = []
        router_ids = [
            r['id'] for r in
            self.clients.neutronclient.list_routers().get('routers')
        ]

        for rid in router_ids:
            for p in ['MGT', 'VRRP']:
                name = 'ASTARA:%s:%s' % (p, rid)
                astara_router_ports += [
                    p['id'] for p in
                    self._admin_clients.neutronclient.list_ports(
                        name=name).get('ports')]

            LOG.debug('Deleting router %s' % rid)
            try:
                self.clients.neutronclient.delete_router(r['id'])
            except neutron_exceptions.NeutronClientException as e:
                if e.status_code == 404:
                    router_ids.remove(rid)
                else:
                    raise e
        self._wait_for_neutron_delete('router', router_ids)

        time.sleep(2)

        port_ids = [
            p['id'] for p in
            self.clients.neutronclient.list_ports().get('ports')]
        for pid in port_ids:
            LOG.debug('Deleting port: %s', pid)
            try:
                self.clients.neutronclient.delete_port(pid)
            except neutron_exceptions.NeutronClientException as e:
                if e.status_code == 404:
                    port_ids.remove(pid)
                else:
                    raise e
        self._wait_for_neutron_delete('port', port_ids)

        subnet_ids = [
            s['id']
            for s in self.clients.neutronclient.list_subnets().get('subnets')]
        for sid in subnet_ids:
            LOG.debug('Deleting subnet: %s', sid)
            try:
                self.clients.neutronclient.delete_subnet(sid)
            except neutron_exceptions.NeutronClientException as e:
                if e.status_code == 404:
                    subnet_ids.remove(sid)
                else:
                    raise e
        self._wait_for_neutron_delete('subnet', subnet_ids)

        # need to make sure the vrrp and mgt ports get deleted
        # in time before the delete_network()
        for p in astara_router_ports:
            try:
                self._admin_clients.neutronclient.delete_port(p)
            except neutron_exceptions.NeutronClientException as e:
                if e.status_code == 404:
                    astara_router_ports.remove(p)
                else:
                    raise e
        self._wait_for_neutron_delete('port', astara_router_ports)

        networks = self.clients.neutronclient.list_networks().get('networks')
        net_ids = [
            n['id'] for n in networks if n['tenant_id'] == self.tenant_id]
        for nid in net_ids:
            LOG.debug('Deleting network: %s', nid)
            try:
                self.clients.neutronclient.delete_network(nid)
            except neutron_exceptions.NeutronClientException as e:
                if e.status_code == 404:
                    net_ids.remove(nid)
                else:
                    raise e

        self._wait_for_neutron_delete('network', net_ids)

    def cleanUp(self):
        self.cleanup_neutron()

        self._admin_ks_client.users.delete(self.user_id)
        self._admin_ks_client.tenants.delete(self.tenant_id)


class AstaraFunctionalBase(testtools.TestCase):
    _test_tenants = []

    def setUp(self):
        super(AstaraFunctionalBase, self).setUp()
        log_format = '%(asctime)s.%(msecs)03d ' + self.id() + ' %(message)s'
        cfg.CONF.set_default('logging_default_format_string', log_format)
        parse_config()
        self.ak_client = astara_client
        self.admin_clients = AdminClientManager()
        self._management_address = None
        self._ssh_client = None

    def ssh_client(self, resource_uuid):
        ssh_client = ssh.Client(
            host=self.get_management_address(resource_uuid),
            username=SSH_USERNAME,
            look_for_keys=True,
        )
        i = 0
        while i <= SSH_TIMEOUT:
            try:
                ssh_client.test_connection_auth()
                return ssh_client
            except tempest_exc.SSHTimeout:
                time.sleep(1)
                i += 1
        raise Exception('SSH connectino timed out after %s sec.')

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

    def get_router_appliance_server(self, resource, uuid, retries=10,
                                    wait_for_active=False):
        """Returns a Nova server object for router"""
        return self.admin_clients.get_router_appliance_server(
            resource, uuid, retries, wait_for_active)

    def get_management_address(self, router_uuid):
        LOG.debug('Getting management address for router %s', router_uuid)
        service_instance = self.get_router_appliance_server(
            resource='router',
            uuid=router_uuid)

        try:
            management_address = service_instance.addresses['mgt'][0]
        except KeyError:
            self.fail('"mgt" port not found on service instance %s (%s)' %
                      (service_instance.id, service_instance.name))

        LOG.debug('Got management address for resource %s', router_uuid)
        return management_address['addr']

    def assert_router_is_active(self, router_uuid):
        i = 0
        res = self.admin_clients.neutronclient.show_router(router_uuid)
        router = res['router']
        LOG.debug('Waiting for resource %s to become ACTIVE', router_uuid)
        while router['status'] != 'ACTIVE':
            if i >= CONF.appliance_active_timeout:
                raise Exception(
                    'Timed out waiting for router %s to become ACTIVE, '
                    'current status=%s' % (router_uuid, router['status']))
            time.sleep(1)
            res = self.admin_clients.neutronclient.show_router(router_uuid)
            router = res['router']
            i += 1
            LOG.debug('Resource %s not active. Status==%s, will wait',
                      router_uuid, router['status'])

    def ping_router_mgt_address(self, router_uuid):
        server = self.get_router_appliance_server('router', router_uuid)
        mgt_interface = server.addresses['mgt'][0]
        program = {4: 'ping', 6: 'ping6'}
        cmd = [program[mgt_interface['version']], '-c5', mgt_interface['addr']]
        LOG.debug('Pinging resource %s: %s', router_uuid, ' '.join(cmd))
        try:
            subprocess.check_call(cmd)
        except:
            raise Exception('Failed to ping router with command: %s' % cmd)

    def address_is_on_subnet(self, address, subnet):
        addr = netaddr.IPNetwork(address)
        sn = netaddr.IPNetwork(subnet)
        return addr.cidr == sn
