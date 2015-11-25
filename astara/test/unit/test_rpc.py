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

from akanda.rug import main  # noqa
from akanda.rug import notifications  # noqa

from oslo_config import cfg
from oslo_config import fixture as config_fixture

import oslo_messaging


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

    @mock.patch.object(rpc, 'get_transport')
    @mock.patch.object(rpc, 'get_target')
    @mock.patch('oslo_messaging.rpc.client.RPCClient')
    def test_get_rpc_client(self, fake_client, fake_get_target,
                            fake_get_transport):
        fake_get_target.return_value = 'fake_target'
        fake_get_transport.return_value = 'fake_transport'
        fake_client.return_value = 'fake_rpc_client'
        res = rpc.get_rpc_client(topic='foo_target', exchange='foo_exchange',
                                 version='2.5')
        fake_get_target.assert_called_with(
            topic='foo_target', exchange='foo_exchange', version='2.5',
            fanout=False,
        )
        self.assertEqual(res, 'fake_rpc_client')
        fake_client.assert_called_with(
            'fake_transport', 'fake_target'
        )

    @mock.patch.object(rpc, 'get_transport')
    @mock.patch('oslo_messaging.notify.Notifier')
    def test_get_rpc_notifier(self, fake_notifier, fake_get_transport):
        fake_get_transport.return_value = 'fake_transport'
        fake_notifier.return_value = 'fake_rpc_notifier'
        res = rpc.get_rpc_notifier(topic='foo_topic')
        self.assertEqual(res, 'fake_rpc_notifier')
        fake_notifier.assert_called_with(
            transport='fake_transport', driver='messaging', topic='foo_topic')


@mock.patch.object(rpc, 'get_transport',
                   mock.MagicMock(return_value='fake_transport'))
@mock.patch.object(rpc, 'get_server',
                   mock.MagicMock(return_value='fake_server'))
@mock.patch.object(rpc, 'get_target',
                   mock.MagicMock(return_value='fake_target'))
class TestConnection(testtools.TestCase):
    def setUp(self):
        super(TestConnection, self).setUp()
        self.connection = rpc.Connection()
        self.config = self.useFixture(config_fixture.Config(cfg.CONF)).config
        self.config(host='test_host')

    def test_create_rpc_consumer(self):
        endpoints = []
        self.connection._add_server_thread = mock.MagicMock()
        self.connection.create_rpc_consumer(
            topic='foo_topic', endpoints=endpoints)
        rpc.get_target.return_value = 'fake_target'
        rpc.get_target.assert_called_with(
            topic='foo_topic', fanout=True, server='test_host')
        rpc.get_server.assert_called_with('fake_target', endpoints)
        self.connection._add_server_thread.assert_called_with('fake_server')

    @mock.patch.object(oslo_messaging, 'get_notification_listener')
    def test_create_notification_listener(self, fake_get_listener):
        endpoints = []
        self.connection._add_server_thread = mock.MagicMock()
        fake_get_listener.return_value = 'fake_listener_server'
        self.connection.create_notification_listener(
            endpoints=[], exchange='foo_exchange', topic='foo_topic')
        self.assertTrue(rpc.get_transport.called)
        rpc.get_target.assert_called_with(
            topic='foo_topic', fanout=False, exchange='foo_exchange')
        fake_get_listener.assert_called_with(
            'fake_transport', ['fake_target'], endpoints,
            pool='akanda.foo_topic.test_host')
        self.connection._add_server_thread.assert_called_with(
            'fake_listener_server')

    @mock.patch('threading.Thread')
    def test__add_server_thread(self, fake_thread):
        fake_thread.return_value = 'fake_server_thread'
        fake_server = mock.MagicMock(
            start=mock.MagicMock()
        )
        self.connection._add_server_thread(fake_server)
        self.assertEqual(
            self.connection._server_threads[fake_server],
            'fake_server_thread')
        fake_thread.assert_called_with(target=fake_server.start)

    def test_consume_in_threads(self):
        fake_server = mock.MagicMock(
            start=mock.MagicMock()
        )
        self.connection._server_threads['foo'] = fake_server
        self.connection.consume_in_threads()
        self.assertTrue(fake_server.start.called)

    def test_close(self):
        fake_server = mock.MagicMock(
            join=mock.MagicMock()
        )
        self.connection._server_threads['foo'] = fake_server
        self.connection.close()
        self.assertTrue(fake_server.join.called)
