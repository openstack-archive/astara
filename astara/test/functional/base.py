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
import six
import subprocess
import testtools
import time

from oslo_config import cfg
from oslo_log import log as logging

from astara.api import astara_client

from keystoneclient import client as _keystoneclient
from keystoneclient import auth as ksauth
from keystoneclient import session as kssession

from neutronclient.v2_0 import client as _neutronclient
from novaclient import client as _novaclient

from keystoneclient import exceptions as ksc_exceptions
from neutronclient.common import exceptions as neutron_exceptions

from tempest_lib.common.utils import data_utils

from astara.test.functional import config

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), 'test.conf')
DEFAULT_ACTIVE_TIMEOUT = 340
DEFAULT_DELETE_TIMEOUT = 60
DEFAULT_DOMAIN = 'default'


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
        'paramiko.transport=INFO',
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
    def auth_version(self):
        if self.auth_url.endswith('v3'):
            return 3
        else:
            return 2.0

    @property
    def keystone_session(self):
        auth_plugin = ksauth.get_plugin_class('password')
        _args = {
            'auth_url': self.auth_url,
            'username': self.username,
            'password': self.password,
        }
        if self.auth_version == 3:
            _args.update({
                'user_domain_name': DEFAULT_DOMAIN,
                'project_domain_name': DEFAULT_DOMAIN,
                'project_name': self.tenant_name,
            })
        else:
            _args.update({
                'tenant_name': self.tenant_name,
            })
        _auth = auth_plugin(**_args)
        return kssession.Session(auth=_auth)

    @property
    def novaclient(self):
        if not self._novaclient:
            self._novaclient = _novaclient.Client(
                version=2,
                session=self.keystone_session,
            )
        return self._novaclient

    @property
    def neutronclient(self):
        if not self._neutronclient:
            self._neutronclient = _neutronclient.Client(
                session=self.keystone_session,
            )
        return self._neutronclient

    @property
    def keystoneclient(self):
        if not self._keystoneclient:
            client = _keystoneclient.Client(session=self.keystone_session)
            self._keystoneclient = client
        return self._keystoneclient

    @property
    def tenant_id(self):
        return self.keystoneclient.tenant_id


class ApplianceServerNotFound(Exception):
    pass


class ApplianceServerTimeout(Exception):
    pass


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

    def get_router_appliance_server(self, router_uuid, retries=10,
                                    wait_for_active=False, ha_router=False):
        """Returns a Nova server object for router"""
        LOG.debug(
            'Looking for nova backing instance for resource %s',
            router_uuid)

        if ha_router:
            exp_instances = 2
        else:
            exp_instances = 1

        for i in six.moves.range(retries):
            service_instances = \
                [instance for instance in
                 self.novaclient.servers.list(
                     search_opts={
                         'all_tenants': 1,
                         'tenant_id': CONF.service_tenant_id}
                 ) if router_uuid in instance.name]

            if service_instances and len(service_instances) == exp_instances:
                LOG.debug(
                    'Found %s backing instance for resource %s: %s',
                    exp_instances, router_uuid, service_instances)
                break
            LOG.debug('%s backing instance not found, will retry %s/%s',
                      exp_instances, i, retries)
            time.sleep(1)
        else:
            raise ApplianceServerNotFound(
                'Could not get nova %s server(s) for router %s' %
                (exp_instances, router_uuid))

        def _wait_for_active(instance):
            LOG.debug('Waiting for backing instance %s to become ACTIVE',
                      instance)
            for i in six.moves.range(CONF.appliance_active_timeout):
                instance = self.novaclient.servers.get(
                    instance.id)
                if instance.status == 'ACTIVE':
                    LOG.debug('Instance %s status==ACTIVE', instance)
                    return
                else:
                    LOG.debug('Instance %s status==%s, will wait',
                              instance, instance.status)
                    time.sleep(1)
            raise ApplianceServerTimeout(
                'Timed out waiting for backing instance of %s %s to become '
                'ACTIVE' % router_uuid)

        if wait_for_active:
            LOG.debug('Waiting for %s backing instances to become ACTIVE',
                      exp_instances)

            [_wait_for_active(i) for i in service_instances]
            LOG.debug('Waiting for backing instance %s to become ACTIVE',
                      exp_instances)

        if ha_router:
            return sorted(service_instances, key=lambda i: i.name)
        else:
            return service_instances[0]


class TestTenant(object):
    def __init__(self):
        parse_config()
        self.username = data_utils.rand_name(name='user', prefix='akanda')
        self.user_id = None
        self.password = data_utils.rand_password()
        self.tenant_name = data_utils.rand_name(name='tenant', prefix='akanda')
        self.tenant_id = None
        self.role_name = data_utils.rand_name(name='role', prefix='akanda')

        self._admin_clients = AdminClientManager()
        self._admin_ks_client = self._admin_clients.keystoneclient
        self.auth_url = self._admin_ks_client.auth_url

        # create the tenant before creating its clients.
        self._create_tenant()

        self.clients = ClientManager(self.username, self.password,
                                     self.tenant_name, self.auth_url)
        self.tester = ClientManager('demo', 'akanda', 'demo', self.auth_url)

        self._subnets = []
        self._routers = []

    def _create_tenant(self):
        if self._admin_clients.auth_version == 3:
            tenant = self._admin_ks_client.projects.create(
                name=self.tenant_name,
                domain=DEFAULT_DOMAIN)
            user = self._admin_ks_client.users.create(
                name=self.username,
                password=self.password,
                project_domain_name=DEFAULT_DOMAIN,
                default_project=self.tenant_name)
            role = self._admin_ks_client.roles.create(name=self.role_name)
            self._admin_ks_client.roles.grant(
                role=role, user=user, project=tenant)
        else:
            tenant = self._admin_ks_client.tenants.create(self.tenant_name)
            self.tenant_id = tenant.id
            user = self._admin_ks_client.users.create(
                name=self.username,
                password=self.password,
                tenant_id=self.tenant_id)
        self.user_id = user.id
        self.tenant_id = tenant.id
        LOG.debug('Created new test tenant: %s (%s)',
                  self.tenant_id, self.user_id)

    def setup_networking(self, ha_router=False):
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
                    'ha': ha_router,
                }
            }
            LOG.debug('Creating router: %s', router_body)
            router = self._admin_clients.neutronclient.create_router(
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
            LOG.debug('Waiting for astara auto-created router')
            for i in six.moves.range(CONF.appliance_active_timeout):
                routers = self.clients.neutronclient.list_routers()
                routers = routers.get('routers')
                if routers:
                    router = routers[0]
                    LOG.debug('Found astara auto-created router: %s', router)
                    break
                else:
                    LOG.debug(
                        'Still waiting for auto-creted router. %s/%s',
                        i, CONF.appliance_active_timeout)
                time.sleep(1)
            else:
                raise Exception('Timed out waiting for default router.')

        # routers report as ACTIVE initially (LP: #1491673)
        time.sleep(2)
        return network, router

    def _wait_for_backing_instance_delete(self, resource_id):
        i = 1
        LOG.debug(
            'Waiting on deletion of backing instance for resource %s',
            resource_id)

        for i in six.moves.range(DEFAULT_DELETE_TIMEOUT):
            try:
                self._admin_clients.get_router_appliance_server(
                    resource_id, retries=1)
            except ApplianceServerNotFound:
                LOG.debug('Backing instance for resource %s deleted',
                          resource_id)
                return

            LOG.debug(
                'Still waiting for deletion of backing instance for %s'
                ' , will wait (%s/%s)',
                resource_id, i, DEFAULT_DELETE_TIMEOUT)
            time.sleep(1)

        m = ('Timed out waiting on deletion of backing instance for %s '
             'after %s sec.' % (resource_id, DEFAULT_DELETE_TIMEOUT))
        LOG.debug(m)
        raise ApplianceServerTimeout(m)

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
                    raise Exception(
                        'Timed out waiting for deletion of %s %s after %s sec.'
                        % (thing, i, max_attempts))
                LOG.debug(
                    'Still waiting for deletion of %s %s, will wait (%s/%s)',
                    thing, i, attempt, max_attempts)
                attempt += 1
                time.sleep(1)

        # also wait for nova backing instance to delete after routers
        if thing in ['router']:
            [self._wait_for_backing_instance_delete(i) for i in ids]

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
        if self._admin_clients.auth_version == 3:
            self._admin_ks_client.projects.delete(self.tenant_id)
        else:
            self._admin_ks_client.tenants.delete(self.tenant_id)

    def router_ha(self, router):
        router = self._admin_clients.neutronclient.show_router(router['id'])
        return router.get('ha', False)

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

    def get_router_appliance_server(self, router_uuid, retries=10,
                                    wait_for_active=False, ha_router=False):
        """Returns a Nova server object for router"""
        return self.admin_clients.get_router_appliance_server(
            router_uuid, retries, wait_for_active, ha_router)

    def get_management_address(self, router_uuid):
        LOG.debug('Getting management address for resource %s', router_uuid)
        if self._management_address:
            return self._management_address['addr']

        service_instance = self.get_router_appliance_server(router_uuid)

        try:
            self._management_address = service_instance.addresses['mgt'][0]
        except KeyError:
            raise Exception(
                '"mgt" port not found on service instance %s (%s)' %
                (service_instance.id, service_instance.name))
        LOG.debug('Got management address for resource %s', router_uuid)
        return self._management_address['addr']

    def assert_router_is_active(self, router_uuid, ha_router=False):
        LOG.debug('Waiting for resource %s to become ACTIVE', router_uuid)
        for i in six.moves.range(CONF.appliance_active_timeout):
            res = self.admin_clients.neutronclient.show_router(router_uuid)
            router = res['router']
            if router['status'] == 'ACTIVE':
                LOG.debug('Router %s ACTIVE after %s sec.', router_uuid, i)
                return

            service_instances = self.get_router_appliance_server(
                router_uuid, ha_router=ha_router)
            if not ha_router:
                service_instances = [service_instances]

            for instance in service_instances:
                if instance.status == 'ERROR':
                    raise Exception(
                        'Backing instance %s for router %s in ERROR state',
                        instance.id, router_uuid)

            LOG.debug(
                'Resource %s not active. Status==%s, will wait, %s/%s sec.',
                router_uuid, router['status'], i,
                CONF.appliance_active_timeout)
            time.sleep(1)

        raise Exception(
            'Timed out waiting for router %s to become ACTIVE, '
            'current status=%s' % (router_uuid, router['status']))

    def ping_router_mgt_address(self, router_uuid):
        server = self.get_router_appliance_server(router_uuid)
        mgt_interface = server.addresses['mgt'][0]
        program = {4: 'ping', 6: 'ping6'}
        cmd = [program[mgt_interface['version']], '-c5', mgt_interface['addr']]
        LOG.debug('Pinging resource %s: %s', router_uuid, ' '.join(cmd))
        try:
            subprocess.check_call(cmd)
        except:
            raise Exception('Failed to ping router with command: %s' % cmd)
