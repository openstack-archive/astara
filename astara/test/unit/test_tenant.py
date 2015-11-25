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

import uuid

import mock
import unittest2 as unittest

from astara import event
from astara import tenant
from astara.drivers import router
from astara import state
from astara.drivers import states
from astara.test.unit import fakes


class TestTenantResourceManager(unittest.TestCase):

    def setUp(self):
        super(TestTenantResourceManager, self).setUp()

        self.fake_driver = fakes.fake_driver()
        self.tenant_id = 'cfb48b9c-66f6-11e5-a7be-525400cfc326'
        self.instance_mgr = \
            mock.patch('astara.instance_manager.InstanceManager').start()
        self.addCleanup(mock.patch.stopall)
        self.notifier = mock.Mock()
        self.trm = tenant.TenantResourceManager(
            '1234',
            notify_callback=self.notifier,
            queue_warning_threshold=10,
            reboot_error_threshold=5,
        )
        self.ctx = mock.Mock()

    def test_new_resource(self):
        r = event.Resource(
            tenant_id=self.tenant_id,
            id='5678',
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sm = self.trm.get_state_machines(msg, self.ctx)[0]
        self.assertEqual(sm.resource_id, '5678')
        self.assertIn('5678', self.trm.state_machines)

    def test_get_state_machine_no_resoruce_id(self):
        r = event.Resource(
            tenant_id=self.tenant_id,
            id=None,
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.assertRaises(tenant.InvalidIncomingMessage,
                          self.trm.get_state_machines, msg, self.ctx)

    def test_all_resources(self):
        for i in range(5):
            rid = str(uuid.uuid4())
            driver = fakes.fake_driver(rid)
            sm = state.Automaton(
                driver=driver,
                worker_context=self.ctx,
                resource_id=driver.id,
                tenant_id=self.tenant_id,
                delete_callback=None,
                bandwidth_callback=None,
                queue_warning_threshold=5,
                reboot_error_threshold=5)
            self.trm.state_machines[rid] = sm
        r = event.Resource(
            tenant_id=self.tenant_id,
            id='*',
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sms = self.trm.get_state_machines(msg, self.ctx)
        self.assertEqual(5, len(sms))

    def test_errored_routers(self):
        self.trm.state_machines.state_machines = {}
        for i in range(5):
            rid = str(uuid.uuid4())
            driver = fakes.fake_driver(rid)
            sm = state.Automaton(
                driver=driver,
                worker_context=self.ctx,
                resource_id=i,
                tenant_id=self.tenant_id,
                delete_callback=None,
                bandwidth_callback=None,
                queue_warning_threshold=5,
                reboot_error_threshold=5)
            self.trm.state_machines[rid] = sm

            # Replace the default mock with one that has 'state' set.
            if i == 2:
                status = states.ERROR
            else:
                status = states.UP

            sm.instance = mock.Mock(state=status)
            self.trm.state_machines.state_machines[str(i)] = sm

        r = event.Resource(
            tenant_id=self.tenant_id,
            id='2',
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sms = self.trm.get_state_machines(msg, self.ctx)
        self.assertEqual(1, len(sms))
        self.assertEqual(2, sms[0].resource_id)
        self.assertIs(self.trm.state_machines.state_machines['2'], sms[0])

    def test_existing_resource(self):
        r = event.Resource(
            tenant_id=self.tenant_id,
            id='5678',
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        # First time creates...
        sm1 = self.trm.get_state_machines(msg, self.ctx)[0]
        # Second time should return the same objects...
        sm2 = self.trm.get_state_machines(msg, self.ctx)[0]
        self.assertIs(sm1, sm2)
        self.assertIs(sm1._queue, sm2._queue)

    def test_existing_resource_of_many(self):
        sms = {}
        for resource_id in ['5678', 'ABCD', 'EFGH']:
            r = event.Resource(
                tenant_id=self.tenant_id,
                id=resource_id,
                driver=router.Router.RESOURCE_NAME,
            )
            msg = event.Event(
                resource=r,
                crud=event.CREATE,
                body={'key': 'value'},
            )
            # First time creates...
            sm1 = self.trm.get_state_machines(msg, self.ctx)[0]
            sms[resource_id] = sm1

        # Second time should return the same objects...
        r = event.Resource(
            id='5678',
            tenant_id=self.tenant_id,
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sm2 = self.trm.get_state_machines(msg, self.ctx)[0]
        self.assertIs(sm2, sms['5678'])

    def test_delete_resource(self):
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_resource('1234')
        self.assertNotIn('1234', self.trm.state_machines)

    def test_delete_default_resource(self):
        self.trm._default_resource_id = '1234'
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_resource('1234')
        self.assertNotIn('1234', self.trm.state_machines)
        self.assertIs(None, self.trm._default_resource_id)

    def test_delete_not_default_resource(self):
        self.trm._default_resource_id = 'abcd'
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_resource('1234')
        self.assertEqual('abcd', self.trm._default_resource_id)

    def test_no_update_deleted_resource(self):
        self.trm._default_resource_id = 'abcd'
        self.trm.state_machines['5678'] = mock.Mock()
        self.trm._delete_resource('5678')
        self.assertEqual(self.trm.state_machines.values(), [])
        r = event.Resource(
            tenant_id='1234',
            id='5678',
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sms = self.trm.get_state_machines(msg, self.ctx)
        self.assertEqual(sms, [])
        self.assertIn('5678', self.trm.state_machines.deleted)

    def test_deleter_callback(self):
        r = event.Resource(
            tenant_id='1234',
            id='5678',
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sm = self.trm.get_state_machines(msg, self.ctx)[0]
        self.assertIn('5678', self.trm.state_machines)
        sm._do_delete()
        self.assertNotIn('5678', self.trm.state_machines)

    def test_report_bandwidth(self):
        notifications = []
        self.notifier.side_effect = notifications.append
        self.trm._report_bandwidth(
            '5678',
            [{'name': 'a',
              'value': 1,
              },
             {'name': 'b',
              'value': 2,
              }],
        )
        n = notifications[0]
        self.assertEqual('1234', n['tenant_id'])
        self.assertIn('5678', n['uuid'])
        self.assertIn('timestamp', n)
        self.assertEqual('astara.bandwidth.used', n['event_type'])
        self.assertIn('a', n['payload'])
        self.assertIn('b', n['payload'])

    def test_get_state_machine_by_resource_id(self):
        fake_sm = mock.Mock()
        self.trm.state_machines['fake_resource_id'] = fake_sm
        self.assertEqual(
            self.trm.get_state_machine_by_resource_id('fake_resource_id'),
            fake_sm
        )
