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


import datetime
import mock
import unittest2 as unittest
from six.moves import builtins as __builtins__
from akanda.rug.api import nova

from novaclient import exceptions as novaclient_exceptions


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
    image={'id': 'fake_image_uuid'}
)

class FakeConf:
    admin_user = 'admin'
    admin_password = 'password'
    admin_tenant_name = 'admin'
    auth_url = 'http://127.0.0.1/'
    auth_strategy = 'keystone'
    auth_region = 'RegionOne'
    router_image_uuid = 'akanda-image'
    router_instance_flavor = 1


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
  - /usr/local/bin/akanda-configure-management aa:aa:aa:aa:aa:aa 192.168.1.1/64

users:
  - name: akanda
    gecos: Akanda
    groups: users
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock-passwd: true
    ssh-authorized-keys:
      - fake_key

final_message: "Akanda appliance is running"
"""


def fake_make_ports_callback():
    return (fake_mgt_port, [fake_ext_port, fake_int_port])


class TestNovaWrapper(unittest.TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        patch = mock.patch('novaclient.v1_1.client.Client')
        self.client = mock.Mock()
        self.client_cls = patch.start()
        self.client_cls.return_value = self.client
        self.nova = nova.Nova(FakeConf)

        self.INSTANCE_INFO = nova.InstanceInfo(
            instance_id='fake_instance_id',
            name='fake_name',
            image_uuid='fake_image_id',
            booting=False,
            last_boot=datetime.datetime.utcnow(),
            ports=(fake_ext_port, fake_int_port),
            management_port=fake_mgt_port,
        )

    @mock.patch.object(nova, '_format_userdata')
    def test_create_instance(self, mock_userdata):
        mock_userdata.return_value = 'fake_userdata'
        expected = [
            mock.call.servers.create(
                'ak-router_id',
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

        self.nova.create_instance(
            'router_id', 'GLANCE-IMAGE-123', fake_make_ports_callback)
        self.client.assert_has_calls(expected)

    def test_get_instance_for_obj(self):
        instance = mock.Mock()
        self.client.servers.list.return_value = [instance]

        expected = [
            mock.call.servers.list(search_opts={'name': 'ak-router_id'})
        ]

        result = self.nova.get_instance_for_obj('router_id')
        self.client.assert_has_calls(expected)
        self.assertEqual(result, instance)

    def test_get_instance_for_obj_not_found(self):
        self.client.servers.list.return_value = []

        expected = [
            mock.call.servers.list(search_opts={'name': 'ak-router_id'})
        ]

        result = self.nova.get_instance_for_obj('router_id')
        self.client.assert_has_calls(expected)
        self.assertIsNone(result)

    def test_get_instance_by_id(self):
        self.client.servers.get.return_value = 'fake_instance'
        expected = [
            mock.call.servers.get('instance_id')
        ]
        result = self.nova.get_instance_by_id('instance_id')
        self.client.servers.get.assert_has_calls(expected)
        self.assertEquals(result, 'fake_instance')

    def test_get_instance_by_id_not_found(self):
        not_found = novaclient_exceptions.NotFound('instance_id')
        self.client.servers.get.side_effect = not_found
        result = self.nova.get_instance_by_id('instance_id')
        self.assertEqual(result, None)

    def test_destroy_router_instance(self):
        self.nova.destroy_instance(self.INSTANCE_INFO)
        self.client.servers.delete.assert_called_with(self.INSTANCE_INFO.id_)

    @mock.patch.object(nova, '_router_ssh_key')
    def test_format_userdata(self, fake_ssh_key):
        fake_ssh_key.return_value = 'fake_key'
        result = nova._format_userdata(fake_int_port)
        self.assertEqual(result.strip(), EXPECTED_USERDATA.strip())

    @mock.patch.object(__builtins__, 'open', autospec=True)
    def test_router_ssh_key(self, fake_open):
        mock_key_file = mock.MagicMock(spec=file)
        mock_key_file.read.return_value = 'fake-key'
        mock_key_file.__enter__.return_value = mock_key_file
        fake_open.return_value = mock_key_file
        result = nova._router_ssh_key()
        self.assertEqual(result, 'fake-key')

    @mock.patch.object(nova, 'LOG', autospec=True)
    @mock.patch.object(__builtins__, 'open', autospec=True)
    def test_router_ssh_key_not_found(self, fake_open, fake_log):
        fake_open.side_effect = IOError
        result = nova._router_ssh_key()
        self.assertEqual(result, '')
        self.assertTrue(fake_log.warning.called)

    @mock.patch.object(nova.Nova, 'create_instance')
    @mock.patch.object(nova.Nova, 'get_instance_for_obj', return_value=None)
    def test_boot_instance(self, fake_get, fake_create_instance):
        fake_create_instance.return_value = 'fake_new_instance_info'
        res = self.nova.boot_instance(
            prev_instance_info=None,
            router_id='foo_router_id',
            router_image_uuid='foo_image',
            make_ports_callback='foo_callback',
        )
        fake_create_instance.assert_called_with(
            'foo_router_id',
            'foo_image',
            'foo_callback',
        )
        fake_get.assert_called_with('foo_router_id')
        self.assertEqual(res, 'fake_new_instance_info')

    @mock.patch.object(nova.Nova, 'create_instance')
    @mock.patch.object(nova.Nova, 'get_instance_for_obj')
    def test_boot_instance_exists(self, fake_get, fake_create_instance):
        fake_instance = fake_nova_instance
        fake_instance.id = 'existing_instance_id'
        fake_instance.status = 'SHUTOFF'
        fake_get.return_value = fake_instance
        fake_create_instance.return_value = 'fake_new_instance_info'
        res = self.nova.boot_instance(
            prev_instance_info=None,
            router_id='foo_router_id',
            router_image_uuid='foo_image',
            make_ports_callback='foo_callback',
        )
        fake_get.assert_called_with('foo_router_id')
        self.client.servers.delete.assert_called_with('existing_instance_id')
        self.assertEqual(res, None)

    @mock.patch.object(nova.Nova, 'create_instance')
    @mock.patch.object(nova.Nova, 'get_instance_for_obj')
    def test_boot_instance_exists_build(self, fake_get, fake_create_instance):
        fake_instance = fake_nova_instance
        fake_instance.id = 'existing_instance_id'
        fake_instance.status = 'BUILD'
        fake_get.return_value = fake_instance
        fake_create_instance.return_value = 'fake_new_instance_info'
        res = self.nova.boot_instance(
            prev_instance_info=None,
            router_id='foo_router_id',
            router_image_uuid='foo_image',
            make_ports_callback='foo_callback',
        )
        fake_get.assert_called_with('foo_router_id')
        self.assertTrue(isinstance(res, nova.InstanceInfo))
        self.assertEqual(res.id_, 'existing_instance_id')
        self.assertEqual(res.name, 'ak-appliance')
        self.assertEqual(res.image_uuid, 'fake_image_uuid')

    @mock.patch.object(nova.Nova, 'create_instance')
    @mock.patch.object(nova.Nova, 'get_instance_by_id', return_value=None)
    def test_boot_instance_prev_inst(self, fake_get, fake_create_instance):
        fake_create_instance.return_value = 'fake_new_instance_info'
        res = self.nova.boot_instance(
            prev_instance_info=self.INSTANCE_INFO,
            router_id='foo_router_id',
            router_image_uuid='foo_image',
            make_ports_callback='foo_callback',
        )
        fake_get.assert_called_with(self.INSTANCE_INFO.id_)
        fake_create_instance.assert_called_with(
            'foo_router_id',
            'foo_image',
            'foo_callback',
        )
        self.assertEqual(res, 'fake_new_instance_info')
    @mock.patch.object(nova.Nova, 'create_instance')
    @mock.patch.object(nova.Nova, 'get_instance_by_id')
    def test_boot_instance_exists_prev_inst(self, fake_get,
                                            fake_create_instance):
        fake_instance = fake_nova_instance
        fake_instance.id = 'existing_instance_id'
        fake_instance.status = 'SHUTOFF'
        fake_get.return_value = fake_instance
        fake_create_instance.return_value = 'fake_new_instance_info'
        res = self.nova.boot_instance(
            prev_instance_info=self.INSTANCE_INFO,
            router_id='foo_router_id',
            router_image_uuid='foo_image',
            make_ports_callback='foo_callback',
        )
        fake_get.assert_called_with(self.INSTANCE_INFO.id_)
        self.client.servers.delete.assert_called_with('existing_instance_id')
        self.assertEqual(res, None)

    @mock.patch.object(nova.Nova, 'create_instance')
    @mock.patch.object(nova.Nova, 'get_instance_by_id')
    def test_boot_instance_exists_build_prev_inst(self, fake_get,
                                                  fake_create_instance):
        fake_instance = fake_nova_instance
        fake_instance.id = 'existing_instance_id'
        fake_instance.status = 'BUILD'
        fake_get.return_value = fake_instance
        fake_create_instance.return_value = 'fake_new_instance_info'
        res = self.nova.boot_instance(
            prev_instance_info=self.INSTANCE_INFO,
            router_id='foo_router_id',
            router_image_uuid='foo_image',
            make_ports_callback='foo_callback',
        )
        # assert we get back the same instance_info but with updated status
        self.assertEqual(res.nova_status, 'BUILD')
        self.assertEqual(res.id_, self.INSTANCE_INFO.id_)
        self.assertTrue(isinstance(res, nova.InstanceInfo))

