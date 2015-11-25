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
import uuid

import multiprocessing

from astara import commands
from astara import event
from astara import notifications
from astara.test.unit import base


CTXT = {
    'read_only': False,
    'domain': None,
    'project_name': 'service',
    'user_id': 'f196eadd630f46bb981b304286689f53',
    'show_deleted': False,
    'roles': ['service'],
    'user_identity': 'f196eadd630f46bb981b304286689f53',
    'project_domain': None,
    'tenant_name': 'service',
    'auth_token': '736751a25b364f28b61947f99e8e1e3f',
    'resource_uuid': None,
    'project_id': '29987e1906a941f8b45c5a3ca38cec8e',
    'tenant_id': '29987e1906a941f8b45c5a3ca38cec8e',
    'is_admin': True, 'user': 'f196eadd630f46bb981b304286689f53',
    'request_id': 'req-ece574ac-b04b-4289-a367-a8b559f72df3',
    'tenant': '29987e1906a941f8b45c5a3ca38cec8e',
    'user_domain': None,
    'timestamp': '2015-06-12 19:00:35.649874',
    'read_deleted': 'no',
    'user_name': 'neutron'
}


class TestGetTenantID(base.RugTestBase):
    def test_notification_tenant_id_from_resource_dict(self):
        for res in ('router', 'port', 'subnet'):
            payload = {
                   res: {
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
                   }
            }
            tenant_id = notifications._get_tenant_id_for_message(CTXT, payload)
            self.assertEqual('c25992581e574b6485dbfdf39a3df46c', tenant_id)

    def test_notification_project_id_from_context(self):
        for ctxt_key in ('tenant_id', 'project_id'):
            payload = {
                   'we_dont_care': {
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
                   }
            }
            tenant_id = notifications._get_tenant_id_for_message(CTXT, payload)
            self.assertEqual(CTXT[ctxt_key], tenant_id)


class TestGetCRUD(base.RugTestBase):
    def setUp(self):
        super(TestGetCRUD, self).setUp()
        self.queue = multiprocessing.Queue()
        self.notifications_endpoint = notifications.NotificationsEndpoint(
            self.queue)
        self.l3_rpc_endpoint = notifications.L3RPCEndpoint(self.queue)

    def _get_event_notification(self, event_type, payload=None):
        # Creates a message /w event_type and payload, sends it through the
        # notifications Endpoint, asserts on its existence in the notifications
        # queue, pops it off and returns it for futher assertions
        payload = payload or {}
        with mock.patch.object(notifications,
                               '_get_tenant_id_for_message') as fake_tenant:

            # events derive tenant id from different parts of the message
            # depending on its format. just mock it out here for consistency
            # across tests. and use a unique id per message to ensure we're
            # popping off the correct message.
            fake_tenant_id = uuid.uuid4().hex
            fake_tenant.return_value = fake_tenant_id
            self.notifications_endpoint.info(
                ctxt=CTXT,
                publisher_id='network.astara',
                event_type=event_type,
                payload=payload, metadata={})
            if not self.queue.qsize():
                # message was discarded and not queued
                return None
            tenant, event = self.queue.get()
            self.assertEqual(tenant, fake_tenant_id)
            return event

    def _get_event_l3_rpc(self, method, **kwargs):
        self.assertTrue(hasattr(self.l3_rpc_endpoint, method))
        f = getattr(self.l3_rpc_endpoint, method)
        kwargs['ctxt'] = CTXT
        with mock.patch.object(notifications,
                               '_get_tenant_id_for_message') as fake_tenant:
            fake_tenant_id = uuid.uuid4().hex
            fake_tenant.return_value = fake_tenant_id
            f(**kwargs)
            if not self.queue.qsize():
                return None
            tenant, event = self.queue.get()
            self.assertEqual(tenant, fake_tenant_id)
            return event

    def test_rpc_router_deleted(self):
        e = self._get_event_l3_rpc(
            method='router_deleted',
            router_id='fake_router_id')
        self.assertEqual(event.DELETE, e.crud)
        self.assertEqual(e.resource.id, 'fake_router_id')

    def test_notification_port(self):
        e = self._get_event_notification('port.create.start')
        self.assertIsNone(e)
        e = self._get_event_notification('port.create.end')
        self.assertEqual(event.UPDATE, e.crud)
        e = self._get_event_notification('port.change.start')
        self.assertIsNone(e)
        e = self._get_event_notification('port.change.end')
        self.assertEqual(event.UPDATE, e.crud)
        e = self._get_event_notification('port.delete.start')
        self.assertIsNone(e)
        e = self._get_event_notification('port.delete.end')
        self.assertEqual(event.UPDATE, e.crud)

    def get_event_notification_subnet(self):
        e = self._get_event_notification('subnet.create.start')
        self.assertFalse(e)
        e = self._get_event_notification('subnet.create.end')
        self.assertEqual(event.UPDATE, e.crud)
        e = self._get_event_notification('subnet.change.start')
        self.assertFalse(e)
        e = self._get_event_notification('subnet.change.end')
        self.assertEqual(event.UPDATE, e.crud)
        e = self._get_event_notification('subnet.delete.start')
        self.assertFalse(e)
        e = self._get_event_notification('subnet.delete.end')
        self.assertEqual(event.UPDATE, e.crud)

    def test_notification_router(self):
        e = self._get_event_notification('router.create.start')
        self.assertFalse(e)
        e = self._get_event_notification('router.create.end')
        self.assertEqual(event.CREATE, e.crud)
        e = self._get_event_notification('router.change.start')
        self.assertFalse(e)
        e = self._get_event_notification('router.change.end')
        self.assertEqual(event.UPDATE, e.crud)
        e = self._get_event_notification('router.delete.start')
        self.assertFalse(e)
        e = self._get_event_notification('router.delete.end')
        self.assertEqual(event.DELETE, e.crud)

    def test_notification_router_id(self):
        payload = {
            u'router': {
                u'admin_state_up': True,
                u'external_gateway_info': None,
                u'id': u'f95fb32d-0072-4675-b4bd-61d829a46aca',
                u'name': u'r2',
                u'ports': [],
                u'status': u'ACTIVE',
                u'tenant_id': u'c25992581e574b6485dbfdf39a3df46c',
            }
        }
        e = self._get_event_notification('router.create.end', payload)
        self.assertEqual(e.resource.id,
                         u'f95fb32d-0072-4675-b4bd-61d829a46aca')

    def test_interface_create_and_delete(self):
        for action in ('create', 'delete'):
            event_type = 'router.interface.%s' % action

            payload = {
                'router.interface': {
                    'subnet_id': u'0535072e-6ef4-4916-b1f5-05fab4da3d0c',
                    'tenant_id': u'c2a1399efbed41e5be2115afa5b5ec25',
                    'port_id': u'63363e5f-59b7-49ca-b619-96c16883b543',
                    'id': u'58868681-4a58-4f69-8dc0-b20955e7923f'
                }
            }
            e = self._get_event_notification(event_type, payload)
            self.assertEqual(event.UPDATE, e.crud)
            self.assertEqual(
                u'58868681-4a58-4f69-8dc0-b20955e7923f',
                e.resource.id
            )

    def test_notification_astara(self):
        e = self._get_event_notification('astara.bandwidth.used')
        self.assertIs(None, e)

    def test_notification_cmd_poll(self):
        event_type = 'astara.command'
        payload = {'command': commands.POLL}
        self.notifications_endpoint.info(
            ctxt=CTXT,
            publisher_id='network.astara',
            event_type=event_type,
            payload=payload, metadata={})
        expected_event = event.Event(
            resource=event.Resource(driver='*', id='*', tenant_id='*'),
            crud=event.POLL,
            body={},
        )
        tenant, e = self.queue.get()
        self.assertEqual('*', tenant)
        self.assertEqual(expected_event, e)
