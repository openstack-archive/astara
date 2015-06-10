# Copyright 2015 Akanda, Inc
#
# Author: Akanda, Inc
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

import mock
import testtools

from akanda.rug.common import rpc

from oslo_config import cfg
from oslo_config import fixture as config_fixture


class TestRPC(testtools.TestCase):
    def setUp(self):
        super(TestRPC, self).setUp()
        self.config = self.useFixture(config_fixture.Config(cfg.CONF)).config

    def test__deprecated_amqp_url_not_set(self):
        self.config(amqp_url=None)
        self.assertIsNone(rpc._deprecated_amqp_url())

    def test__deprecated_amqp_url(self):
        self.config(amqp_url='amqp://stackrabbit:secretrabbit@127.0.0.1:/')
        self.assertEqual(rpc._deprecated_amqp_url(),
                         'rabbit://stackrabbit:secretrabbit@127.0.0.1:5672/')

    @mock.patch('oslo_messaging.get_transport')
    @mock.patch.object(rpc, '_deprecated_amqp_url')
    def test_get_transport(self, fake_amqp_url, fake_get_transport):
        fake_amqp_url.return_value = 'fake_url'
        fake_get_transport.return_value = 'fake_transport'
        transport = rpc.get_transport()
        self.assertEqual(transport, 'fake_transport')
        fake_get_transport.assert_called_with(conf=cfg.CONF, url='fake_url')

    @mock.patch.object(rpc, 'get_transport')
    @mock.patch('oslo_messaging.get_rpc_server')
    def test_get_server(self, fake_get_server, fake_get_transport):
        fake_get_transport.return_value = 'fake_transport'
        fake_get_server.return_value = 'fake_server'
        fake_endpoints = [1, 2]
        result = rpc.get_server(target='fake_target', endpoints=fake_endpoints)
        self.assertEqual(result, 'fake_server')
        fake_get_server.assert_called_with(
            transport='fake_transport',
            target='fake_target',
            endpoints=fake_endpoints,
        )

    @mock.patch('oslo_messaging.Target')
    def test_get_target(self, fake_target):
        fake_target.return_value = 'fake_target'
        target_args = {
            'topic': 'fake_topic',
            'fanout': False,
            'exchange': 'fake_exchange',
            'version': 'fake_version',
            'server': 'fake_server',
        }
        result = rpc.get_target(**target_args)
        self.assertEqual(result, 'fake_target')
        fake_target.assert_called_with(**target_args)
