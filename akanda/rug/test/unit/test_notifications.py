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


import mock
import socket

import unittest2 as unittest

from akanda.rug import event
from akanda.rug import notifications


class TestGetTenantID(unittest.TestCase):

    def test_rpc(self):
        msg = {'_context_is_admin': False,
               '_context_project_id': 'c25992581e574b6485dbfdf39a3df46c',
               '_context_read_deleted': 'no',
               '_context_roles': ['anotherrole', 'Member', 'admin'],
               '_context_tenant_id': 'c25992581e574b6485dbfdf39a3df46c',
               '_context_timestamp': '2013-07-25 13:51:50.791338',
               '_context_user_id': '472511eedebd4322a26c5fb1f52711ee',
               '_unique_id': 'c87303336c7c4bb0b097b3e97bebf7ea',
               'args': {'router_id': 'f37f31e9-adc2-4712-a002-4ccf0be17a99'},
               'method': 'router_deleted',
               'version': '1.0'}
        tenant_id = notifications._get_tenant_id_for_message(msg)
        self.assertEqual("c25992581e574b6485dbfdf39a3df46c", tenant_id)

    def test_notification_tenant_id(self):
        msg = {u'_context_is_admin': False,
               u'_context_read_deleted': u'no',
               u'_context_roles': [u'anotherrole', u'Member'],
               u'_context_tenant_id': u'c25992581e574b6485dbfdf39a3df46c',
               u'_context_timestamp': u'2013-07-25 14:02:55.073049',
               u'_context_user_id': u'472511eedebd4322a26c5fb1f52711ee',
               u'_unique_id': u'8825f8a6ccec4285a7ecfdad7bd53815',
               u'event_type': u'port.create.end',
               u'message_id': u'bb9bcf1d-1547-4867-b41e-f5298fa10869',
               u'payload': {
                   u'port': {
                       u'admin_state_up': True,
                       u'device_id': u'',
                       u'device_owner': u'',
                       u'fixed_ips': [{
                           u'ip_address': u'192.168.123.3',
                           u'subnet_id': u'53d8a76a-3e1a-43e0-975e-83a4b464d18c',  # noqa
                       }],
                       u'id': u'bbd92f5a-5a1d-4ec5-9272-8e4dd5f0c084',
                       u'mac_address': u'fa:16:3e:f4:81:a9',
                       u'name': u'',
                       u'network_id': u'c3a30111-dd52-405c-84b2-4d62068e2d35',  # noqa
                       u'security_groups': [u'5124be1c-b2d5-47e6-ac62-411a0ea028c8'],  # noqa
                       u'status': u'DOWN',
                       u'tenant_id': u'c25992581e574b6485dbfdf39a3df46c',
                   },
               },
               u'priority': u'INFO',
               u'publisher_id': u'network.akanda',
               u'timestamp': u'2013-07-25 14:02:55.244126'}
        tenant_id = notifications._get_tenant_id_for_message(msg)
        self.assertEqual('c25992581e574b6485dbfdf39a3df46c', tenant_id)

    def test_notification_project_id(self):
        msg = {
            u'_context_is_admin': False,
            u'_context_project_id': u'c25992581e574b6485dbfdf39a3df46c',
            u'_context_read_deleted': u'no',
            u'_context_roles': [u'anotherrole', u'Member'],
            u'_context_timestamp': u'2013-07-25 14:02:55.073049',
            u'_context_user_id': u'472511eedebd4322a26c5fb1f52711ee',
            u'_unique_id': u'8825f8a6ccec4285a7ecfdad7bd53815',
            u'event_type': u'port.create.end',
            u'message_id': u'bb9bcf1d-1547-4867-b41e-f5298fa10869',
            u'payload': {
                u'port': {
                    u'admin_state_up': True,
                    u'device_id': u'',
                    u'device_owner': u'',
                    u'fixed_ips': [{
                        u'ip_address': u'192.168.123.3',
                        u'subnet_id': u'53d8a76a-3e1a-43e0-975e-83a4b464d18c'}],  # noqa
                    u'id': u'bbd92f5a-5a1d-4ec5-9272-8e4dd5f0c084',
                    u'mac_address': u'fa:16:3e:f4:81:a9',
                    u'name': u'',
                    u'network_id': u'c3a30111-dd52-405c-84b2-4d62068e2d35',
                    u'security_groups': [u'5124be1c-b2d5-47e6-ac62-411a0ea028c8'],  # noqa
                    u'status': u'DOWN',
                    u'tenant_id': u'c25992581e574b6485dbfdf39a3df46c',
                },
            },
            u'priority': u'INFO',
            u'publisher_id': u'network.akanda',
            u'timestamp': u'2013-07-25 14:02:55.244126'}

        tenant_id = notifications._get_tenant_id_for_message(msg)
        self.assertEqual('c25992581e574b6485dbfdf39a3df46c', tenant_id)

    def test_notification_with_tenant_id_from_router_dict(self):
        msg = {
            u'_context_roles': [u'admin', u'_member_'],
            u'priority': u'INFO',
            u'_context_read_deleted': u'no',
            u'event_type': u'router.update.end',
            u'timestamp': u'2013-10-20 17:07:14.573678',
            u'_context_tenant_id': u'618cb69189144d4bbabe0aaa678d48c6',
            u'payload': {
                u'router': {
                    u'status': u'ACTIVE',
                    u'external_gateway_info': {
                        u'network_id': u'8e163d8b-81a8-4f4f-b622-ecbf452de2e9'
                    },
                    u'name': u'r',
                    u'admin_state_up': True,
                    u'tenant_id': u'cddd1d8533cc4f828837d4c2dcb7ef96',
                    u'id': u'64009064-be1e-44e2-9e5d-1c706cef2e34',
                    u'routes': [],
                }
            },
            u'_unique_id': u'1cc91b54bd2947fb9d513e67795ebb8d',
            u'_context_is_admin': True,
            u'_context_project_id': u'618cb69189144d4bbabe0aaa678d48c6',
            u'_context_timestamp': u'2013-10-20 17:07:14.349210',
            u'_context_user_id': u'a5b54cb8fb3a4cb49ba6118f3d2e35af',
            u'publisher_id': u'network.orange.localdomain',
            u'message_id': u'd8335b96-0fde-461a-af65-3f1aaa73c8af'
        }
        tenant_id = notifications._get_tenant_id_for_message(msg)
        self.assertEqual('cddd1d8533cc4f828837d4c2dcb7ef96', tenant_id)


class TestGetCRUD(unittest.TestCase):

    def test_rpc_router_deleted(self):
        msg = {u'oslo.message': u'{"_context_roles": ["anotherrole", "Member", "admin"], "_context_read_deleted": "no", "args": {"router_id": "f37f31e9-adc2-4712-a002-4ccf0be17a99"}, "_unique_id": "c87303336c7c4bb0b097b3e97bebf7ea", "_context_timestamp": "2013-07-25 13:51:50.791338", "_context_is_admin": false, "version": "1.0", "_context_project_id": "c25992581e574b6485dbfdf39a3df46c", "_context_tenant_id": "c25992581e574b6485dbfdf39a3df46c", "_context_user_id": "472511eedebd4322a26c5fb1f52711ee", "method": "router_deleted"}', u'oslo.version': u'2.0'}  # noqa
        e = notifications._make_event_from_message(msg)
        self.assertEqual(event.DELETE, e.crud)
        self.assert_(e.router_id)

    def _test_notification(self, event_type):
        msg = {
            u'_context_is_admin': False,
            u'_context_project_id': u'c25992581e574b6485dbfdf39a3df46c',
            u'_context_read_deleted': u'no',
            u'_context_roles': [u'anotherrole', u'Member'],
            u'_context_timestamp': u'2013-07-25 14:02:55.073049',
            u'_context_user_id': u'472511eedebd4322a26c5fb1f52711ee',
            u'_unique_id': u'8825f8a6ccec4285a7ecfdad7bd53815',
            u'event_type': event_type,
            u'message_id': u'bb9bcf1d-1547-4867-b41e-f5298fa10869',
            u'payload': {
                u'port': {
                    u'admin_state_up': True,
                    u'device_id': u'',
                    u'device_owner': u'',
                    u'fixed_ips': [{
                        u'ip_address': u'192.168.123.3',
                        u'subnet_id': u'53d8a76a-3e1a-43e0-975e-83a4b464d18c'}],  # noqa
                    u'id': u'bbd92f5a-5a1d-4ec5-9272-8e4dd5f0c084',
                    u'mac_address': u'fa:16:3e:f4:81:a9',
                    u'name': u'',
                    u'network_id': u'c3a30111-dd52-405c-84b2-4d62068e2d35',
                    u'security_groups': [u'5124be1c-b2d5-47e6-ac62-411a0ea028c8'],  # noqa
                    u'status': u'DOWN',
                    u'tenant_id': u'c25992581e574b6485dbfdf39a3df46c',
                },
            },
            u'priority': u'INFO',
            u'publisher_id': u'network.akanda',
            u'timestamp': u'2013-07-25 14:02:55.244126'}
        return notifications._make_event_from_message(msg)

    def test_notification_port(self):
        e = self._test_notification('port.create.start')
        self.assertFalse(e)
        e = self._test_notification('port.create.end')
        self.assertEqual(event.UPDATE, e.crud)
        e = self._test_notification('port.change.start')
        self.assertFalse(e)
        e = self._test_notification('port.change.end')
        self.assertEqual(event.UPDATE, e.crud)
        e = self._test_notification('port.delete.start')
        self.assertFalse(e)
        e = self._test_notification('port.delete.end')
        self.assertEqual(event.UPDATE, e.crud)

    def test_notification_subnet(self):
        e = self._test_notification('subnet.create.start')
        self.assertFalse(e)
        e = self._test_notification('subnet.create.end')
        self.assertEqual(event.UPDATE, e.crud)
        e = self._test_notification('subnet.change.start')
        self.assertFalse(e)
        e = self._test_notification('subnet.change.end')
        self.assertEqual(event.UPDATE, e.crud)
        e = self._test_notification('subnet.delete.start')
        self.assertFalse(e)
        e = self._test_notification('subnet.delete.end')
        self.assertEqual(event.UPDATE, e.crud)

    def test_notification_router(self):
        e = self._test_notification('router.create.start')
        self.assertFalse(e)
        e = self._test_notification('router.create.end')
        self.assertEqual(event.CREATE, e.crud)
        e = self._test_notification('router.change.start')
        self.assertFalse(e)
        e = self._test_notification('router.change.end')
        self.assertEqual(event.UPDATE, e.crud)
        e = self._test_notification('router.delete.start')
        self.assertFalse(e)
        e = self._test_notification('router.delete.end')
        self.assertEqual(event.DELETE, e.crud)

    def test_notification_router_id(self):
        msg = {
            u'_context_is_admin': False,
            u'_context_project_id': u'c25992581e574b6485dbfdf39a3df46c',
            u'_context_read_deleted': u'no',
            u'_context_roles': [u'anotherrole', u'Member'],
            u'_context_tenant_id': u'c25992581e574b6485dbfdf39a3df46c',
            u'_context_timestamp': u'2013-08-01 20:17:11.569282',
            u'_context_user_id': u'472511eedebd4322a26c5fb1f52711ee',
            u'_unique_id': u'246f69b5dff44156ba56c4a2b7c3d47f',
            u'event_type': u'router.create.end',
            u'message_id': u'658c8901-6858-4dbc-be8a-242d94fc4b5d',
            u'payload': {
                u'router': {
                    u'admin_state_up': True,
                    u'external_gateway_info': None,
                    u'id': u'f95fb32d-0072-4675-b4bd-61d829a46aca',
                    u'name': u'r2',
                    u'ports': [],
                    u'status': u'ACTIVE',
                    u'tenant_id': u'c25992581e574b6485dbfdf39a3df46c',
                },
            },
            u'priority': u'INFO',
            u'publisher_id': u'network.akanda',
            u'timestamp': u'2013-08-01 20:17:11.662425',
        }

        e = notifications._make_event_from_message(msg)
        self.assertEqual(e.router_id, u'f95fb32d-0072-4675-b4bd-61d829a46aca')

    def test_interface_create_and_delete(self):
        for action in ('create', 'delete'):
            msg = {
                u'_context_roles': [u'_member_', u'admin'],
                u'priority': u'INFO',
                u'_context_read_deleted': u'no',
                u'event_type': u'router.interface.%s' % action,
                u'timestamp': u'2014-04-08 17:48:42.917596',
                u'_context_tenant_id': u'4838397648d946279ad422886aabcf07',
                u'payload': {
                    u'router.interface': {
                        u'subnet_id': u'0535072e-6ef4-4916-b1f5-05fab4da3d0c',
                        u'tenant_id': u'c2a1399efbed41e5be2115afa5b5ec25',
                        u'port_id': u'63363e5f-59b7-49ca-b619-96c16883b543',
                        u'id': u'58868681-4a58-4f69-8dc0-b20955e7923f'
                    }
                },
                u'_unique_id': u'bf7cbac3c964442b841f8a0dfda1b84f',
                u'_context_is_admin': True,
                u'_context_project_id': u'4838397648d946279ad422886aabcf07',
                u'_context_timestamp': u'2014-04-08 17:48:42.838558',
                u'_context_user_id': u'22a73cb6a5bf493da6a1b0b602b61ed6',
                u'publisher_id': u'network.akanda',
                u'message_id': u'c441df90-404a-4b53-a4d6-67f042339ef2'
            }
            e = notifications._make_event_from_message(msg)
            self.assertEqual(event.UPDATE, e.crud)
            self.assertEqual(
                u'58868681-4a58-4f69-8dc0-b20955e7923f',
                e.router_id
            )

    def test_notification_akanda(self):
        e = self._test_notification('akanda.bandwidth.used')
        self.assertIs(None, e)


class TestSend(unittest.TestCase):

    @mock.patch('kombu.connection.BrokerConnection')
    @mock.patch('kombu.entity.Exchange')
    @mock.patch('kombu.Producer')
    def setUp(self, producer_cls, exchange, broker):
        super(TestSend, self).setUp()
        self.messages = []
        self.producer = mock.Mock()
        self.producer.publish.side_effect = self.messages.append
        producer_cls.return_value = self.producer
        self.notifier = notifications.Publisher('url', 'quantum', 'topic')
        self.notifier.start()
        self.addCleanup(self.notifier.stop)

    # def tearDown(self):
    #     if self.notifier:
    #         self.notifier.stop()
    #     super(TestSend, self).tearDown()

    def test_payload(self):
        self.notifier.publish({'payload': 'message here'})
        self.notifier.stop()  # flushes the queue
        msg = self.messages[0]
        self.assertEqual(msg['payload'], 'message here')

    def test_context(self):
        self.notifier.publish({'payload': 'message here'})
        self.notifier.stop()  # flushes the queue
        msg = self.messages[0]
        self.assertIn('_context_tenant', msg)

    def test_unique_id(self):
        self.notifier.publish({'payload': 'message here'})
        self.notifier.publish({'payload': 'message here'})
        self.notifier.stop()  # flushes the queue
        msg1, msg2 = self.messages
        self.assertNotEqual(msg1['_unique_id'], msg2['_unique_id'])


class TestListen(unittest.TestCase):

    @mock.patch('kombu.connection.BrokerConnection')
    def test_ensure_connection_is_called(self, mock_broker):
        broker = mock_broker.return_value
        broker.ensure_connection = mock.Mock()
        broker.drain_events = mock.Mock(side_effect=SystemExit())
        notification_queue = mock.MagicMock()

        notifications.listen('test-host', 'amqp://test.host',
                             'test-notifications', 'test-rpc',
                             notification_queue)

        broker.ensure_connection.assert_called_once_with(
            errback=mock.ANY,
            max_retries=10,
            interval_start=2,
            interval_step=2,
            interval_max=30)

    @mock.patch('kombu.connection.BrokerConnection')
    def test_establish_new_connection_after_socket_timeout(self, mock_broker):
        broker = mock_broker.return_value
        broker.ensure_connection = mock.Mock()
        broker.drain_events = mock.Mock(
            side_effect=(socket.timeout(), SystemExit()))
        notification_queue = mock.MagicMock()

        notifications.listen('test-host', 'amqp://test.host',
                             'test-notifications', 'test-rpc',
                             notification_queue)

        self.assertEqual(broker.ensure_connection.call_args_list,
                         [mock.call(errback=mock.ANY,
                                    max_retries=10,
                                    interval_start=2,
                                    interval_step=2,
                                    interval_max=30),
                          mock.call(errback=mock.ANY,
                                    max_retries=10,
                                    interval_start=2,
                                    interval_step=2,
                                    interval_max=30)])
