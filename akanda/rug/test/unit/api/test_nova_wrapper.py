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

from akanda.rug.api import nova


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


class FakeConf:
    admin_user = 'admin'
    admin_password = 'password'
    admin_tenant_name = 'admin'
    auth_url = 'http://127.0.0.1/'
    auth_strategy = 'keystone'
    auth_region = 'RegionOne'
    router_image_uuid = 'akanda-image'
    router_instance_flavor = 1

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

        self.nova.create_instance('router_id', 'GLANCE-IMAGE-123', fake_make_ports_callback)
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

    def test_destroy_router_instance(self):
        self.nova.destroy_instance(self.INSTANCE_INFO)
        self.client.servers.delete.assert_called_with(self.INSTANCE_INFO.id_)
