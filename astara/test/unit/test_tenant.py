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

from six.moves import range
from astara import event
from astara import tenant
from astara.drivers import router
from astara import state
from astara.drivers import states
from astara.test.unit import base, fakes


class TestTenantResourceManager(base.RugTestBase):

    def setUp(self):
        super(TestTenantResourceManager, self).setUp()

        self.fake_driver = fakes.fake_driver()
        self.load_resource_p = mock.patch(
            'astara.tenant.TenantResourceManager._load_resource_from_message')
        self.fake_load_resource = self.load_resource_p.start()
        self.fake_load_resource.return_value = self.fake_driver

        self.tenant_id = 'cfb48b9c-66f6-11e5-a7be-525400cfc326'
        self.instance_mgr = \
            mock.patch('astara.instance_manager.InstanceManager').start()
        self.addCleanup(mock.patch.stopall)
        self.notifier = mock.Mock()
        self.deleter = mock.Mock()
        self.trm = tenant.TenantResourceManager(
            '1234',
            delete_callback=self.deleter,
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
        self.fake_load_resource.return_value = fakes.fake_driver(
            resource_id='5678')
        sm = self.trm.get_state_machines(msg, self.ctx)[0]
        self.assertEqual('5678', sm.resource_id)
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
                resource=driver,
                worker_context=self.ctx,
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
                resource=driver,
                worker_context=self.ctx,
                tenant_id=self.tenant_id,
                delete_callback=None,
                bandwidth_callback=None,
                queue_warning_threshold=5,
                reboot_error_threshold=5)
            self.trm.state_machines[rid] = sm

            # Replace the default mock with one that has 'state' set.
            if i == 2:
                status = states.ERROR
                err_id = sm.resource_id
            else:
                status = states.UP

            sm.instance = mock.Mock(state=status)
            self.trm.state_machines.state_machines[sm.resource_id] = sm

        r = event.Resource(
            tenant_id=self.tenant_id,
            id=err_id,
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sms = self.trm.get_state_machines(msg, self.ctx)
        self.assertEqual(1, len(sms))
        self.assertEqual(err_id, sms[0].resource_id)
        self.assertIs(self.trm.state_machines.state_machines[err_id], sms[0])

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
        r = event.Resource(
            id='1234',
            tenant_id=self.tenant_id,
            driver=router.Router.RESOURCE_NAME,
        )
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_resource(r)
        self.assertNotIn('1234', self.trm.state_machines)
        self.assertTrue(self.deleter.called)

    def test_delete_default_resource(self):
        r = event.Resource(
            id='1234',
            tenant_id=self.tenant_id,
            driver=router.Router.RESOURCE_NAME)
        self.trm._default_resource_id = '1234'
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_resource(r)
        self.assertNotIn('1234', self.trm.state_machines)
        self.assertIs(None, self.trm._default_resource_id)

    def test_delete_not_default_resource(self):
        r = event.Resource(
            id='1234',
            tenant_id=self.tenant_id,
            driver=router.Router.RESOURCE_NAME)
        self.trm._default_resource_id = 'abcd'
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_resource(r)
        self.assertEqual('abcd', self.trm._default_resource_id)

    def test_no_update_deleted_resource(self):
        r = event.Resource(
            tenant_id='1234',
            id='5678',
            driver=router.Router.RESOURCE_NAME,
        )
        self.trm._default_resource_id = 'abcd'
        self.trm.state_machines['5678'] = mock.Mock()
        self.trm._delete_resource(r)
        self.assertEqual([], self.trm.state_machines.values())
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
        self.assertEqual([], sms)
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
        self.assertTrue(
            self.trm.state_machines.has_been_deleted('5678'))

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
            fake_sm,
            self.trm.get_state_machine_by_resource_id('fake_resource_id'))

    def test_unmanage_resource(self):
        fake_sm = mock.Mock()
        self.trm.state_machines['fake-resource_id'] = fake_sm
        self.trm.unmanage_resource('fake-resource-id')
        self.assertNotIn('fake-resource-id', self.trm.state_machines)
        self.assertFalse(
            self.trm.state_machines.has_been_deleted('fake-resource-id'))

    @mock.patch('astara.drivers.load_from_byonf')
    @mock.patch('astara.drivers.get')
    def test__load_driver_from_message_no_byonf(self, fake_get, fake_byonf):
        self.load_resource_p.stop()
        self.config(enable_byonf=False)
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
        fake_driver = mock.Mock()
        fake_driver.return_value = 'fake_driver'
        fake_get.return_value = fake_driver

        self.assertEqual(
            'fake_driver',
            self.trm._load_resource_from_message(self.ctx, msg))
        fake_get.assert_called_with(msg.resource.driver)
        fake_driver.assert_called_with(self.ctx, msg.resource.id)
        self.assertFalse(fake_byonf.called)

    @mock.patch('astara.drivers.load_from_byonf')
    @mock.patch('astara.drivers.get')
    def test__load_driver_from_message_with_byonf(self, fake_get, fake_byonf):
        self.load_resource_p.stop()
        self.config(enable_byonf=True)
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
        fake_driver = mock.Mock()
        fake_byonf.return_value = fake_driver

        self.ctx.neutron.tenant_has_byo_for_function.return_value = 'byonf_res'
        self.assertEqual(
            fake_driver, self.trm._load_resource_from_message(self.ctx, msg))
        fake_byonf.assert_called_with(
            self.ctx, 'byonf_res', msg.resource.id)
        self.assertFalse(fake_get.called)

    @mock.patch('astara.drivers.load_from_byonf')
    @mock.patch('astara.drivers.get')
    def test__load_driver_from_message_empty_byonf(self, fake_get, fake_byonf):
        self.load_resource_p.stop()
        self.config(enable_byonf=True)
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

        fake_driver = mock.Mock()
        fake_driver.return_value = 'fake_fallback_driver'
        fake_get.return_value = fake_driver

        self.ctx.neutron.tenant_has_byo_for_function.return_value = None
        self.assertEqual(
            'fake_fallback_driver',
            self.trm._load_resource_from_message(self.ctx, msg))
        fake_get.assert_called_with(msg.resource.driver)
