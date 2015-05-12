
import ConfigParser
import mock
import os
import testtools

from akanda.rug.api import akanda_client

from novaclient.v1_1 import client as _novaclient
from neutronclient.v2_0 import client as _neutronclient

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), 'test.conf')


def get_config():
        config_file = os.environ.get('AKANDA_TEST_CONFIG',
                                     DEFAULT_CONFIG)
        config = ConfigParser.SafeConfigParser()
        if not config.read(config_file):
            self.skipTest('Skipping, no test config found @ %s' % config_file)

        conf_settings = ['os_auth_url', 'os_username', 'os_password',
                         'os_tenant_name', 'service_tenant_name',
                         'service_tenant_id', 'appliance_api_port']
        out = {}
        for c in conf_settings:
            try:
                out[c] = config.get('functional', c)
            except ConfigParser.NoOptionError:
                out[c] = None
        missing = [k for k, v in out.items() if not v]
        if missing:
                self.fail('Missing required setting in test.conf (%s)'
                          (config_file, ','.join(missing)))
        return out

class AkandaFunctionalBase(testtools.TestCase):
    def setUp(self):
        super(AkandaFunctionalBase, self).setUp()
        self.config = get_config()

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

    @property
    def management_address(self):
        if self._management_address:
            return self._management_address['addr']

        #TODO(adam_g): Deal with multiple service VMs
        service_vm = [vm for vm in self.novaclient.servers.list(search_opts={
            'all_tenants': 1,
            'tenant_id': self.config['service_tenant_id'],
        }) if vm.name.startswith('ak-')][0]

        try:
            self._management_address = service_vm.addresses['mgt'][0]
        except KeyError:
            self.fail('"mgt" port not found on service vm %s (%s)' %
                      (service_vm.id, service_vm.name))
        return self._management_address['addr']
