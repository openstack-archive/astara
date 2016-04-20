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


from datetime import datetime, timedelta

import mock
import copy
from novaclient import exceptions as novaclient_exceptions
from six.moves import builtins as __builtins__

from astara.api import nova
from astara.test.unit import base


class FakeNovaServer(object):
    id = '6f05906e-4538-11e5-bb22-5254003ff1ae'
    name = 'ak-796aafbc-4538-11e5-88e0-5254003ff1ae'
    image = {'id': '83031410-4538-11e5-abd2-5254003ff1ae'}
    status = 'ACTIVE'
    created = '2012-08-20T21:11:09Z'


class FakeModel(object):
    def __init__(self, id_, **kwargs):
        self.id = id_
        self.__dict__.update(kwargs)


fake_ext_port = FakeModel(
    '1',
    mac_address='aa:bb:cc:dd:ee:ff',
    network_id='ext-net',
    fixed_ips=[FakeModel('', ip_address='9.9.9.9', subnet_id='s2')])

fake_mgt_port = FakeModel(
    '2',
    mac_address='aa:bb:cc:cc:bb:aa',
    network_id='mgt-net')

fake_int_port = FakeModel(
    '3',
    mac_address='aa:aa:aa:aa:aa:aa',
    network_id='int-net',
    fixed_ips=[FakeModel('', ip_address='192.168.1.1', subnet_id='s1')])

fake_router = FakeModel(
    'router_id',
    tenant_id='tenant_id',
    external_port=fake_ext_port,
    management_port=fake_mgt_port,
    internal_ports=[fake_int_port],
    ports=[fake_mgt_port, fake_ext_port, fake_int_port])

fake_nova_instance = FakeModel(
    'instance_id',
    name='ak-appliance',
    status=None,
    image={'id': 'fake_image_uuid'},
    created='2012-08-20T21:11:09Z'
)


class FakeConf:
    admin_user = 'admin'
    admin_password = 'password'
    admin_tenant_name = 'admin'
    auth_url = 'http://127.0.0.1/'
    auth_strategy = 'keystone'
    auth_region = 'RegionOne'
    router_image_uuid = 'astara-image'
    router_instance_flavor = 1
    instance_provider = 'foo'
    endpoint_type = 'publicURL'


EXPECTED_USERDATA = """
#cloud-config

cloud_config_modules:
  - emit_upstart
  - set_hostname
  - locale
  - set-passwords
  - timezone
  - disable-ec2-metadata
  - runcmd

output: {all: '| tee -a /var/log/cloud-init-output.log'}

debug:
  - verbose: true

bootcmd:
  - /usr/local/bin/astara-configure-management aa:aa:aa:aa:aa:aa 192.168.1.1/64

users:
  - name: astara
    gecos: Astara
    groups: users
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock-passwd: true
    ssh-authorized-keys:
      - fake_key

final_message: "Astara appliance is running"
"""


def fake_make_ports_callback():
    return (fake_mgt_port, [fake_ext_port, fake_int_port])


class TestNovaWrapper(base.RugTestBase):
    def setUp(self):
        super(TestNovaWrapper, self).setUp()
        self.addCleanup(mock.patch.stopall)
        patch = mock.patch('novaclient.client.Client')
        self.client = mock.Mock()
        self.client_cls = patch.start()
        self.client_cls.return_value = self.client

        self.fake_instance_provider = mock.Mock(create_instance=mock.Mock())
        fake_instance_provider_cls = mock.Mock(name='fake_provider_class')
        fake_instance_provider_cls.return_value = \
            self.fake_instance_provider
        get_instance_provider_p = mock.patch.object(
            nova, 'get_instance_provider').start()
        get_instance_provider_p.return_value = fake_instance_provider_cls

        self.nova = nova.Nova(FakeConf)

        self.INSTANCE_INFO = nova.InstanceInfo(
            instance_id='fake_instance_id',
            name='fake_name',
            image_uuid='fake_image_id',
            status='ACTIVE',
            last_boot=(datetime.utcnow() - timedelta(minutes=15)),
            ports=[fake_int_port, fake_ext_port, fake_mgt_port],
            management_port=fake_mgt_port,
        )

    def test_get_instance_for_obj(self):
        instance = mock.Mock()
        self.client.servers.list.return_value = [instance]

        expected = [
            mock.call.servers.list(search_opts={'name': 'foo_instance_name'})
        ]

        result = self.nova.get_instance_for_obj('foo_instance_name')
        self.client.assert_has_calls(expected)
        self.assertEqual(result, instance)

    def test_get_instance_for_obj_not_found(self):
        self.client.servers.list.return_value = []

        expected = [
            mock.call.servers.list(search_opts={'name': 'foo_instance_name'})
        ]

        result = self.nova.get_instance_for_obj('foo_instance_name')
        self.client.assert_has_calls(expected)
        self.assertIsNone(result)

    def test_get_instance_by_id(self):
        self.client.servers.get.return_value = 'fake_instance'
        expected = [
            mock.call.servers.get('instance_id')
        ]
        result = self.nova.get_instance_by_id('instance_id')
        self.client.servers.get.assert_has_calls(expected)
        self.assertEqual(result, 'fake_instance')

    def test_get_instance_by_id_not_found(self):
        not_found = novaclient_exceptions.NotFound('instance_id')
        self.client.servers.get.side_effect = not_found
        result = self.nova.get_instance_by_id('instance_id')
        self.assertIsNone(result)

    def test_destroy_instance(self):
        self.nova.destroy_instance(self.INSTANCE_INFO)
        self.client.servers.delete.assert_called_with(self.INSTANCE_INFO.id_)

    @mock.patch.object(nova, '_ssh_key')
    def test_format_userdata(self, fake_ssh_key):
        fake_ssh_key.return_value = 'fake_key'
        result = nova.format_userdata(fake_int_port)
        self.assertEqual(result.strip(), EXPECTED_USERDATA.strip())

    @mock.patch.object(__builtins__, 'open', autospec=True)
    def test_ssh_key(self, fake_open):
        mock_key_file = mock.MagicMock(spec=file)
        mock_key_file.read.return_value = 'fake-key'
        mock_key_file.__enter__.return_value = mock_key_file
        fake_open.return_value = mock_key_file
        result = nova._ssh_key()
        self.assertEqual(result, 'fake-key')

    @mock.patch.object(nova, 'LOG', autospec=True)
    @mock.patch.object(__builtins__, 'open', autospec=True)
    def test_ssh_key_not_found(self, fake_open, fake_log):
        fake_open.side_effect = IOError
        result = nova._ssh_key()
        self.assertEqual(result, '')
        self.assertTrue(fake_log.warning.called)

    @mock.patch.object(nova.Nova, 'get_instance_for_obj', return_value=None)
    def test_boot_instance(self, fake_get):
        self.fake_instance_provider.create_instance.return_value = \
            'fake_new_instance_info'
        res = self.nova.boot_instance(
            resource_type='router',
            prev_instance_info=None,
            name='foo_instance_name',
            image_uuid='foo_image',
            flavor='foo_flavor',
            make_ports_callback='foo_callback',
        )
        self.fake_instance_provider.create_instance.assert_called_with(
            resource_type='router',
            name='foo_instance_name',
            image_uuid='foo_image',
            flavor='foo_flavor',
            make_ports_callback='foo_callback',
        )
        fake_get.assert_called_with('foo_instance_name')
        self.assertEqual(res, 'fake_new_instance_info')

    @mock.patch.object(nova.Nova, 'get_instance_for_obj')
    def test_boot_instance_exists(self, fake_get):
        fake_instance = fake_nova_instance
        fake_instance.id = 'existing_instance_id'
        fake_instance.status = 'SHUTOFF'
        fake_get.return_value = fake_instance
        self.fake_instance_provider.create_instance.return_value = \
            'fake_new_instance_info'
        res = self.nova.boot_instance(
            resource_type='router',
            prev_instance_info=None,
            name='foo_instance_name',
            image_uuid='foo_image',
            flavor='foo_flavor',
            make_ports_callback='foo_callback',
        )
        fake_get.assert_called_with('foo_instance_name')
        self.client.servers.delete.assert_called_with('existing_instance_id')
        self.assertIsNone(res)

    @mock.patch.object(nova.Nova, 'get_instance_for_obj')
    def test_boot_instance_exists_build(self, fake_get):
        fake_instance = fake_nova_instance
        fake_instance.id = 'existing_instance_id'
        fake_instance.status = 'BUILD'
        fake_get.return_value = fake_instance
        self.fake_instance_provider.create_instance.return_value = \
            'fake_new_instance_info'
        res = self.nova.boot_instance(
            resource_type='router',
            prev_instance_info=None,
            name='foo_instance_name',
            image_uuid='foo_image',
            flavor='foo_flavor',
            make_ports_callback='foo_callback',
        )
        fake_get.assert_called_with('foo_instance_name')
        self.assertIsInstance(res, nova.InstanceInfo)
        self.assertEqual(res.id_, 'existing_instance_id')
        self.assertEqual(res.name, 'ak-appliance')
        self.assertEqual(res.image_uuid, 'fake_image_uuid')

    @mock.patch.object(nova.Nova, 'get_instance_by_id', return_value=None)
    def test_boot_instance_prev_inst(self, fake_get):
        self.fake_instance_provider.create_instance.return_value = \
            'fake_new_instance_info'
        res = self.nova.boot_instance(
            resource_type='router',
            prev_instance_info=self.INSTANCE_INFO,
            name='foo_instance_name',
            image_uuid='foo_image',
            flavor='foo_flavor',
            make_ports_callback='foo_callback',
        )
        fake_get.assert_called_with(self.INSTANCE_INFO.id_)
        self.fake_instance_provider.create_instance.assert_called_with(
            resource_type='router',
            name='foo_instance_name',
            image_uuid='foo_image',
            flavor='foo_flavor',
            make_ports_callback='foo_callback',
        )
        self.assertEqual(res, 'fake_new_instance_info')

    @mock.patch.object(nova.Nova, 'get_instance_by_id')
    def test_boot_instance_exists_prev_inst(self, fake_get):
        fake_instance = fake_nova_instance
        fake_instance.id = 'existing_instance_id'
        fake_instance.status = 'SHUTOFF'
        fake_get.return_value = fake_instance
        self.fake_instance_provider.create_instance.return_value = \
            'fake_new_instance_info'
        res = self.nova.boot_instance(
            resource_type='router',
            prev_instance_info=self.INSTANCE_INFO,
            name='foo_instance_name',
            image_uuid='foo_image',
            flavor='foo_flavor',
            make_ports_callback='foo_callback',
        )
        fake_get.assert_called_with(self.INSTANCE_INFO.id_)
        self.client.servers.delete.assert_called_with('existing_instance_id')
        self.assertIsNone(res)

    @mock.patch.object(nova.Nova, 'get_instance_for_obj')
    def test_boot_instance_exists_build_prev_inst(self, fake_get):
        fake_instance = fake_nova_instance
        fake_instance.id = 'existing_instance_id'
        fake_instance.status = 'BUILD'
        fake_get.return_value = fake_instance
        self.fake_instance_provider.create_instance.return_value = \
            'fake_new_instance_info'
        res = self.nova.boot_instance(
            resource_type='router',
            prev_instance_info=None,
            name='foo_instance_name',
            image_uuid='foo_image',
            flavor='foo_flavor',
            make_ports_callback='foo_callback',
        )
        # assert we get back the same instance_info but with updated status
        self.assertEqual(res.nova_status, 'BUILD')
        self.assertEqual(res.id_, fake_instance.id)
        self.assertIsInstance(res, nova.InstanceInfo)

    def test_from_nova(self):
        fake_server = FakeNovaServer()
        last_boot = datetime.strptime(
            fake_server.created, "%Y-%m-%dT%H:%M:%SZ")
        instance_info = nova.InstanceInfo.from_nova(fake_server)
        self.assertEqual(fake_server.id, instance_info.id_)
        self.assertEqual(fake_server.name, instance_info.name)
        self.assertEqual(fake_server.image['id'], instance_info.image_uuid)
        self.assertEqual(last_boot, instance_info.last_boot)

    def test_booting_false(self):
        self.INSTANCE_INFO.nova_status = 'ACTIVE'
        self.assertFalse(self.INSTANCE_INFO.booting)

    def test_booting_true(self):
        self.INSTANCE_INFO.nova_status = 'BUILDING'
        self.assertTrue(self.INSTANCE_INFO.booting)

    def test_no_provider_not_none(self):
        NoProviderConf = copy.deepcopy(FakeConf)
        del NoProviderConf.instance_provider
        self.nova = nova.Nova(NoProviderConf)
        self.assertIsNotNone(self.nova.instance_provider.create_instance)


class TestOnDemandInstanceProvider(base.RugTestBase):
    def setUp(self):
        super(TestOnDemandInstanceProvider, self).setUp()
        self.addCleanup(mock.patch.stopall)
        patch = mock.patch('novaclient.client.Client')
        self.client = mock.Mock()
        self.client_cls = patch.start()
        self.client_cls.return_value = self.client

    @mock.patch.object(nova, 'format_userdata')
    def test_create_instance(self, mock_userdata):
        provider = nova.OnDemandInstanceProvider(self.client)
        self.client.servers.create.return_value = fake_nova_instance
        mock_userdata.return_value = 'fake_userdata'
        expected = [
            mock.call.servers.create(
                'ak-instance-name',
                nics=[{'port-id': '2',
                       'net-id': 'mgt-net',
                       'v4-fixed-ip': ''},
                      {'port-id': '1',
                       'net-id': 'ext-net',
                       'v4-fixed-ip': ''},
                      {'port-id': '3',
                       'net-id': 'int-net',
                       'v4-fixed-ip': ''}],
                flavor=1,
                image='GLANCE-IMAGE-123',
                config_drive=True,
                userdata='fake_userdata',
            )
        ]

        provider.create_instance(
            'router', 'ak-instance-name', 'GLANCE-IMAGE-123',
            1, fake_make_ports_callback)
        self.client.assert_has_calls(expected)


class TestPezInstanceProvider(base.RugTestBase):
    def setUp(self):
        super(TestPezInstanceProvider, self).setUp()
        self.addCleanup(mock.patch.stopall)
        patch = mock.patch('novaclient.client.Client')
        self.nova_client = mock.Mock()
        self.nova_client_cls = patch.start()
        self.nova_client_cls.return_value = self.nova_client

        patch = mock.patch('astara.pez.rpcapi.AstaraPezAPI')
        self.rpc_client = mock.Mock()
        self.rpc_client_cls = patch.start()
        self.rpc_client_cls.return_value = self.rpc_client

    @mock.patch.object(nova, 'format_userdata')
    def test_create_instance(self, mock_userdata):
        provider = nova.PezInstanceProvider(self.nova_client)

        inst_port = {
            'id': '1',
            'name': 'name',
            'device_id': 'device_id',
            'fixed_ips': [{'ip_address': '192.168.1.1', 'subnet_id': 'sub1'}],
            'mac_address': 'aa:bb:cc:dd:ee:ff',
            'network_id': 'net_id',
            'device_owner': 'test'
        }
        mgt_port = {
            'id': '2',
            'name': 'name',
            'device_id': 'device_id',
            'fixed_ips': [{'ip_address': '192.168.1.10', 'subnet_id': 'sub1'}],
            'mac_address': 'aa:bb:cc:dd:ee:fa',
            'network_id': 'net_id2',
            'device_owner': 'test'
        }

        fake_server = FakeNovaServer()
        self.nova_client.servers.get.return_value = fake_server
        fake_pez_instance = {
            'id': fake_server.id,
            'management_port': mgt_port,
            'instance_ports': [inst_port],
        }
        self.rpc_client.get_instance.return_value = fake_pez_instance
        res = provider.create_instance(
            'router', 'ak-instance-name', 'GLANCE-IMAGE-123',
            1, fake_make_ports_callback)
        self.rpc_client.get_instance.assert_called_with(
            'router', 'ak-instance-name',
            {'network_id': 'mgt-net', 'id': '2'},
            [{'network_id': 'ext-net', 'id': '1'},
             {'network_id': 'int-net', 'id': '3'}])
        self.nova_client.servers.get.assert_called_with(fake_server.id)
        exp_instance_info = nova.InstanceInfo.from_nova(fake_server)
        self.assertEqual(exp_instance_info.id_, res.id_)
