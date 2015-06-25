
import ConfigParser
import mock
import os
import testtools
import time

from akanda.rug.api import akanda_client

from novaclient.v1_1 import client as _novaclient
from neutronclient.v2_0 import client as _neutronclient

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), 'test.conf')
DEFAULT_ACTIVE_TIMEOUT = 340


class AkandaFunctionalBase(testtools.TestCase):
    def setUp(self):
        super(AkandaFunctionalBase, self).setUp()
        self.config = self._get_config()

        self.ak_cfg = mock.patch.object(akanda_client.cfg, 'CONF').start()
        self.ak_cfg.alive_timeout = 10
        self.ak_client = akanda_client

        self.novaclient = _novaclient.Client(
            self.config['os_username'],
            self.config['os_password'],
            self.config['os_tenant_name'],
            auth_url=self.config['os_auth_url'],
            auth_system='keystone',
        )

        self.neutronclient = _neutronclient.Client(
            username=self.config['os_username'],
            password=self.config['os_password'],
            tenant_name=self.config['os_tenant_name'],
            auth_url=self.config['os_auth_url'],
            auth_strategy='keystone',
        )
        self._management_address = None

    def _get_config(self):
            config_file = os.environ.get('AKANDA_TEST_CONFIG',
                                         DEFAULT_CONFIG)
            config = ConfigParser.SafeConfigParser()
            if not config.read(config_file):
                self.skipTest('Skipping, no test config found @ %s' %
                              config_file)

            req_conf_settings = ['os_auth_url', 'os_username', 'os_password',
                                 'os_tenant_name', 'service_tenant_name',
                                 'service_tenant_id', 'appliance_api_port',
                                 'akanda_test_router_uuid']
            out = {}
            for c in req_conf_settings:
                try:
                    out[c] = config.get('functional', c)
                except ConfigParser.NoOptionError:
                    out[c] = None
            missing = [k for k, v in out.items() if not v]
            if missing:
                    self.fail('Missing required setting in test.conf (%s)'
                              (config_file, ','.join(missing)))

            opt_conf_settings = {
                'appliance_active_timeout': DEFAULT_ACTIVE_TIMEOUT,
            }
            for setting, default in opt_conf_settings.items():
                try:
                    out[setting] = config.get('functional', setting)
                except ConfigParser.NoOptionError:
                    out[setting] = default
            return out

    @property
    def management_address(self):
        if self._management_address:
            return self._management_address['addr']

        # TODO(adam_g): Deal with multiple service instances
        service_instance = [instance for instance in \
                            self.novaclient.servers.list(search_opts={
            'all_tenants': 1,
            'tenant_id': self.config['service_tenant_id'],
        }) if instance.name.startswith('ak-')][0]

        try:
            self._management_address = service_instance.addresses['mgt'][0]
        except KeyError:
            self.fail('"mgt" port not found on service instance %s (%s)' %
                      (service_instance.id, service_instance.name))
        return self._management_address['addr']

    def assert_router_is_active(self, router_uuid=None):
        if not router_uuid:
            router_uuid = self.config['akanda_test_router_uuid']
        i = 0
        router = self.neutronclient.show_router(router_uuid)['router']
        while router['status'] != 'ACTIVE':
            if i >= int(self.config['appliance_active_timeout']):
                raise Exception(
                    'Timed out waiting for router %s to become ACTIVE, '
                    'current status=%s' % (router_uuid, router['status']))
            time.sleep(1)
            router = self.neutronclient.show_router(router_uuid)['router']
            i += 1
