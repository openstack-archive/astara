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
from oslo_config import cfg
from oslo_config import fixture as config_fixture
import oslo_messaging
import testtools

from astara.common import rpc
from astara import main  # noqa
from astara import notifications  # noqa


class TestRPC(testtools.TestCase):
    def setUp(self):
        super(TestRPC, self).setUp()
        self.config = self.useFixture(config_fixture.Config(cfg.CONF)).config

    def test__deprecated_amqp_url_not_set(self):
        self.config(amqp_url=None)
        self.assertIsNone(rpc._deprecated_amqp_url())

    def test__deprecated_amqp_url(self):
        self.config(amqp_url='amqp://stackrabbit:secretrabbit@127.0.0.1:/')
        self.assertEqual('rabbit://stackrabbit:secretrabbit@127.0.0.1:5672/',
                        rpc._deprecated_amqp_url())

    @mock.patch('oslo_messaging.get_transport')
    @mock.patch.object(rpc, '_deprecated_amqp_url')
    def test_get_transport(self, fake_amqp_url, fake_get_transport):
        fake_amqp_url.return_value = 'fake_url'
        fake_get_transport.return_value = 'fake_transport'
        transport = rpc.get_transport()
        self.assertEqual('fake_transport', transport)
        fake_get_transport.assert_called_with(conf=cfg.CONF, url='fake_url')

    @mock.patch.object(rpc, 'get_transport')
    @mock.patch('oslo_messaging.get_rpc_server')
    def test_get_server(self, fake_get_server, fake_get_transport):
        fake_get_transport.return_value = 'fake_transport'
        fake_get_server.return_value = 'fake_server'
        fake_endpoints = [1, 2]
        result = rpc.get_server(target='fake_target', endpoints=fake_endpoints)
        self.assertEqual('fake_server', result)
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
        self.assertEqual('fake_target', result)
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
        self.assertEqual('fake_rpc_client', res)
        fake_client.assert_called_with(
            'fake_transport', 'fake_target'
        )

    @mock.patch.object(rpc, 'get_transport')
    @mock.patch('oslo_messaging.notify.Notifier')
    def test_get_rpc_notifier(self, fake_notifier, fake_get_transport):
        fake_get_transport.return_value = 'fake_transport'
        fake_notifier.return_value = 'fake_rpc_notifier'
        res = rpc.get_rpc_notifier(topic='foo_topic')
        self.assertEqual('fake_rpc_notifier', res)
        fake_notifier.assert_called_with(
            transport='fake_transport', driver='messaging', topic='foo_topic')


@mock.patch.object(rpc, 'get_transport',
                   mock.MagicMock(return_value='fake_transport'))
@mock.patch.object(rpc, 'get_server',
                   mock.MagicMock(return_value='fake_server'))
@mock.patch.object(rpc, 'get_target',
                   mock.MagicMock(return_value='fake_target'))
class TestMessagingService(testtools.TestCase):
    def setUp(self):
        super(TestMessagingService, self).setUp()
        self.connection = rpc.MessagingService()
        self.config = self.useFixture(config_fixture.Config(cfg.CONF)).config
        self.config(host='test_host')

    def test_create_rpc_consumer(self):
        endpoints = []
        self.connection._add_server = mock.MagicMock()
        self.connection.create_rpc_consumer(
            topic='foo_topic', endpoints=endpoints)
        rpc.get_target.return_value = 'fake_target'
        rpc.get_target.assert_called_with(
            topic='foo_topic', fanout=True, server='test_host')
        rpc.get_server.assert_called_with('fake_target', endpoints)
        self.connection._add_server.assert_called_with('fake_server')

    @mock.patch.object(oslo_messaging, 'get_notification_listener')
    def test_create_notification_listener(self, fake_get_listener):
        endpoints = []
        self.connection._add_server = mock.MagicMock()
        fake_get_listener.return_value = 'fake_listener_server'
        self.connection.create_notification_listener(
            endpoints=[], exchange='foo_exchange', topic='foo_topic')
        self.assertTrue(rpc.get_transport.called)
        rpc.get_target.assert_called_with(
            topic='foo_topic', fanout=False, exchange='foo_exchange')
        fake_get_listener.assert_called_with(
            'fake_transport', ['fake_target'], endpoints,
            pool='astara.foo_topic.test_host', executor='threading')
        self.connection._add_server.assert_called_with(
            'fake_listener_server')

    def test__add_server(self):
        fake_server = mock.MagicMock(
            start=mock.MagicMock())
        self.connection._add_server(fake_server)
        self.assertIn(
            fake_server,
            self.connection._servers)

    def test_start(self):
        fake_server = mock.MagicMock(
            start=mock.MagicMock()
        )
        self.connection._add_server(fake_server)
        self.connection.start()
        self.assertTrue(fake_server.start.called)

    def test_stop(self):
        fake_server = mock.MagicMock(
            stop=mock.MagicMock()
        )
        self.connection._add_server(fake_server)
        self.connection.stop()
        self.assertTrue(fake_server.wait.called)
