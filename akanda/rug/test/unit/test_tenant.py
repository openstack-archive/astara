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
import unittest2 as unittest

from akanda.rug import event
from akanda.rug import tenant
from akanda.rug import state
from akanda.rug import vm_manager


class TestTenantRouterManager(unittest.TestCase):

    def setUp(self):
        super(TestTenantRouterManager, self).setUp()

        self.vm_mgr = mock.patch('akanda.rug.vm_manager.VmManager').start()
        self.addCleanup(mock.patch.stopall)
        self.notifier = mock.Mock()
        self.trm = tenant.TenantRouterManager(
            '1234',
            notify_callback=self.notifier,
            queue_warning_threshold=10,
            reboot_error_threshold=5,
        )
        # Establish a fake default router for the tenant for tests
        # that try to use it. We mock out the class above to avoid
        # errors instantiating the client without enough config
        # settings, but we have to attach to the mock instance created
        # when we set the return value for get_router_for_tenant().
        self.ctx = mock.Mock()
        self.default_router = mock.MagicMock(name='default_router')
        self.default_router.configure_mock(id='9ABC')
        grt = self.ctx.neutron.get_router_for_tenant
        grt.return_value = self.default_router

    def test_new_router(self):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
            lbaas=False,
        )
        sm = self.trm.get_state_machines(msg, self.ctx)[0]
        self.assertEqual(sm.router_id, '5678')
        self.assertIn('5678', self.trm.state_machines)

    def test_default_router(self):
        msg = event.Event(
            tenant_id='1234',
            router_id=None,
            crud=event.CREATE,
            body={'key': 'value'},
            lbaas=False,
        )
        sm = self.trm.get_state_machines(msg, self.ctx)[0]
        self.assertEqual(sm.router_id, self.default_router.id)
        self.assertIn(self.default_router.id, self.trm.state_machines)

    def test_all_routers(self):
        self.trm.state_machines.state_machines = {
            str(i): state.Automaton(str(i), '1234', None, None, None, 5, 5)
            for i in range(5)
        }
        msg = event.Event(
            tenant_id='1234',
            router_id='*',
            crud=event.CREATE,
            body={'key': 'value'},
            lbaas=False,
        )
        sms = self.trm.get_state_machines(msg, self.ctx)
        self.assertEqual(5, len(sms))

    def test_errored_routers(self):
        self.trm.state_machines.state_machines = {}
        for i in range(5):
            sm = state.Automaton(str(i), '1234', None, None, None, 5, 5)
            # Replace the default mock with one that has 'state' set.
            if i == 2:
                status = vm_manager.ERROR
            else:
                status = vm_manager.UP
            sm.vm = mock.Mock(state=status)
            self.trm.state_machines.state_machines[str(i)] = sm
        msg = event.Event(
            tenant_id='1234',
            router_id='error',
            crud=event.CREATE,
            body={'key': 'value'},
            lbaas=False,
        )
        sms = self.trm.get_state_machines(msg, self.ctx)
        self.assertEqual(1, len(sms))
        self.assertEqual('2', sms[0].router_id)
        self.assertIs(self.trm.state_machines.state_machines['2'], sms[0])

    def test_existing_router(self):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
            lbaas=False,
        )
        # First time creates...
        sm1 = self.trm.get_state_machines(msg, self.ctx)[0]
        # Second time should return the same objects...
        sm2 = self.trm.get_state_machines(msg, self.ctx)[0]
        self.assertIs(sm1, sm2)
        self.assertIs(sm1._queue, sm2._queue)

    def test_existing_router_of_many(self):
        sms = {}
        for router_id in ['5678', 'ABCD', 'EFGH']:
            msg = event.Event(
                tenant_id='1234',
                router_id=router_id,
                crud=event.CREATE,
                body={'key': 'value'},
                lbaas=False,
            )
            # First time creates...
            sm1 = self.trm.get_state_machines(msg, self.ctx)[0]
            sms[router_id] = sm1
        # Second time should return the same objects...
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
            lbaas=False,
        )
        sm2 = self.trm.get_state_machines(msg, self.ctx)[0]
        self.assertIs(sm2, sms['5678'])

    def test_delete_router(self):
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_router('1234')
        self.assertNotIn('1234', self.trm.state_machines)

    def test_delete_default_router(self):
        self.trm._default_router_id = '1234'
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_router('1234')
        self.assertNotIn('1234', self.trm.state_machines)
        self.assertIs(None, self.trm._default_router_id)

    def test_delete_not_default_router(self):
        self.trm._default_router_id = 'abcd'
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_router('1234')
        self.assertEqual('abcd', self.trm._default_router_id)

    def test_no_update_deleted_router(self):
        self.trm._default_router_id = 'abcd'
        self.trm.state_machines['5678'] = mock.Mock()
        self.trm._delete_router('5678')
        self.assertEqual(self.trm.state_machines.values(), [])
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
            lbaas=False,
        )
        sms = self.trm.get_state_machines(msg, self.ctx)
        self.assertEqual(sms, [])
        self.assertIn('5678', self.trm.state_machines.deleted)

    def test_deleter_callback(self):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
            lbaas=False,
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
        self.assertIn('5678', n['router_id'])
        self.assertIn('timestamp', n)
        self.assertEqual('akanda.bandwidth.used', n['event_type'])
        self.assertIn('a', n['payload'])
        self.assertIn('b', n['payload'])
