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


import logging
from collections import deque

import mock
import unittest2 as unittest

from akanda.rug import event
from akanda.rug import state
from akanda.rug import vm_manager
from akanda.rug.api.quantum import RouterGone


class BaseTestStateCase(unittest.TestCase):
    state_cls = state.State

    def setUp(self):
        self.ctx = mock.Mock()  # worker context
        log = logging.getLogger(__name__)
        vm_mgr_cls = mock.patch('akanda.rug.vm_manager.VmManager').start()
        self.addCleanup(mock.patch.stopall)
        self.vm = vm_mgr_cls.return_value
        self.params = state.StateParams(
            vm=self.vm,
            log=log,
            queue=deque(),
            bandwidth_callback=mock.Mock(),
            reboot_error_threshold=3,
        )
        self.state = self.state_cls(self.params)

    def _test_transition_hlpr(self, action, expected_class,
                              vm_state=state.vm_manager.UP):
        self.vm.state = vm_state
        self.assertIsInstance(
            self.state.transition(action, self.ctx),
            expected_class
        )


class TestBaseState(BaseTestStateCase):
    def test_execute(self):
        self.assertEqual(
            self.state.execute('action', self.ctx),
            'action'
        )

    def test_transition(self):
        self.assertEqual(
            self.state.transition('action', self.ctx),
            self.state
        )


class TestCalcActionState(BaseTestStateCase):
    state_cls = state.CalcAction

    def _test_hlpr(self, expected_action, queue_states,
                   leftover=0, initial_action=event.POLL):
        self.params.queue = deque(queue_states)
        self.assertEqual(
            self.state.execute(initial_action, self.ctx),
            expected_action
        )
        self.assertEqual(len(self.params.queue), leftover)

    def test_execute_empty_queue(self):
        self._test_hlpr('testaction', [], initial_action='testaction')

    def test_execute_delete_in_queue(self):
        self._test_hlpr(event.DELETE, [event.CREATE, event.DELETE], 2)

    def test_none_start_action_update(self):
        self._test_hlpr(expected_action=event.UPDATE,
                        queue_states=[event.UPDATE, event.UPDATE],
                        leftover=0,
                        initial_action=None)

    def test_none_start_action_poll(self):
        self._test_hlpr(expected_action=event.POLL,
                        queue_states=[event.POLL, event.POLL],
                        leftover=0,
                        initial_action=None)

    def test_execute_ignore_pending_update_follow_create(self):
        self._test_hlpr(event.CREATE, [event.CREATE, event.UPDATE])

    def test_execute_upgrade_to_create_follow_update(self):
        self._test_hlpr(event.CREATE, [event.UPDATE, event.CREATE])

    def test_execute_collapse_same_events(self):
        events = [event.UPDATE, event.UPDATE, event.UPDATE]
        self._test_hlpr(event.UPDATE, events, 0)

    def test_execute_collapse_mixed_events(self):
        events = [
            event.UPDATE,
            event.POLL,
            event.UPDATE,
            event.POLL,
            event.UPDATE,
            event.READ,
        ]
        self._test_hlpr(event.UPDATE, events, 1)

    def test_execute_events_ending_with_poll(self):
        events = [
            event.UPDATE,
            event.UPDATE,
            event.POLL,
            event.POLL,
        ]
        self._test_hlpr(event.UPDATE, events, 0)

    def test_transition_update_missing_router_down(self):
        self.ctx.neutron = mock.Mock()
        self.ctx.neutron.get_router_detail.side_effect = RouterGone
        self._test_transition_hlpr(
            event.UPDATE,
            state.CheckBoot,
            vm_manager.BOOTING
        )

    def test_transition_update_missing_router_not_down(self):
        self.ctx.neutron = mock.Mock()
        self.ctx.neutron.get_router_detail.side_effect = RouterGone
        self._test_transition_hlpr(
            event.UPDATE,
            state.CheckBoot,
            vm_manager.BOOTING
        )

    def test_transition_delete_missing_router_down(self):
        self.ctx.neutron = mock.Mock()
        self.ctx.neutron.get_router_detail.side_effect = RouterGone
        self._test_transition_hlpr(
            event.DELETE,
            state.StopVM,
            vm_manager.DOWN
        )

    def test_transition_delete_missing_router_not_down(self):
        self.ctx.neutron = mock.Mock()
        self.ctx.neutron.get_router_detail.side_effect = RouterGone
        self._test_transition_hlpr(
            event.DELETE,
            state.StopVM,
            vm_manager.BOOTING
        )

    def test_transition_delete_down_vm(self):
        self._test_transition_hlpr(event.DELETE, state.StopVM, vm_manager.DOWN)

    def test_transition_delete_up_vm(self):
        self._test_transition_hlpr(event.DELETE, state.StopVM)

    def test_transition_create_down_vm(self):
        for evt in [event.POLL, event.READ, event.UPDATE, event.CREATE]:
            self._test_transition_hlpr(evt, state.CreateVM, vm_manager.DOWN)

    def test_transition_poll_up_vm(self):
        self._test_transition_hlpr(event.POLL, state.Alive, vm_manager.UP)

    def test_transition_poll_configured_vm(self):
        self._test_transition_hlpr(
            event.POLL,
            state.Alive,
            vm_manager.CONFIGURED
        )

    def test_transition_other_up_vm(self):
        for evt in [event.READ, event.UPDATE, event.CREATE]:
            self._test_transition_hlpr(evt, state.Alive)


class TestAliveState(BaseTestStateCase):
    state_cls = state.Alive

    def test_execute(self):
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough'
        )
        self.vm.update_state.assert_called_once_with(self.ctx)

    def test_transition_vm_down(self):
        for evt in [event.POLL, event.READ, event.UPDATE, event.CREATE]:
            self._test_transition_hlpr(evt, state.CreateVM, vm_manager.DOWN)

    def test_transition_poll_vm_configured(self):
        self._test_transition_hlpr(
            event.POLL,
            state.CalcAction,
            vm_manager.CONFIGURED
        )

    def test_transition_read_vm_configured(self):
        self._test_transition_hlpr(
            event.READ,
            state.ReadStats,
            vm_manager.CONFIGURED
        )

    def test_transition_up_to_configured(self):
        self._test_transition_hlpr(
            event.CREATE,
            state.ConfigureVM,
            vm_manager.UP
        )

    def test_transition_configured_vm_configured(self):
        self._test_transition_hlpr(
            event.CREATE,
            state.ConfigureVM,
            vm_manager.CONFIGURED
        )


class TestCreateVMState(BaseTestStateCase):
    state_cls = state.CreateVM

    def test_execute(self):
        self.vm.attempts = 0
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough'
        )
        self.vm.boot.assert_called_once_with(self.ctx)

    def test_execute_too_many_attempts(self):
        self.vm.attempts = self.params.reboot_error_threshold
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough'
        )
        self.assertEqual([], self.vm.boot.mock_calls)
        self.vm.set_error.assert_called_once_with(self.ctx)

    def test_transition_vm_down(self):
        self._test_transition_hlpr(
            event.READ,
            state.CheckBoot,
            vm_manager.DOWN
        )

    def test_transition_vm_up(self):
        self._test_transition_hlpr(event.READ, state.CheckBoot)

    def test_transition_vm_error(self):
        self._test_transition_hlpr(event.READ, state.CalcAction,
                                   vm_state=state.vm_manager.ERROR)


class TestRebuildVMState(BaseTestStateCase):
    state_cls = state.RebuildVM

    def test_execute(self):
        self.assertEqual(
            self.state.execute('ignored', self.ctx),
            event.CREATE,
        )
        self.vm.stop.assert_called_once_with(self.ctx)

    def test_execute_after_error(self):
        self.vm.state = vm_manager.ERROR
        self.assertEqual(
            self.state.execute('ignored', self.ctx),
            event.CREATE,
        )
        self.vm.stop.assert_called_once_with(self.ctx)
        self.vm.clear_error.assert_called_once_with(self.ctx)

    def test_execute_gone(self):
        self.vm.state = vm_manager.GONE
        self.assertEqual(
            self.state.execute('ignored', self.ctx),
            event.DELETE,
        )
        self.vm.stop.assert_called_once_with(self.ctx)


class TestCheckBootState(BaseTestStateCase):
    state_cls = state.CheckBoot

    def test_execute(self):
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough'
        )
        self.vm.check_boot.assert_called_once_with(self.ctx)
        assert list(self.params.queue) == ['passthrough']

    def test_transition_vm_configure(self):
        self._test_transition_hlpr(
            event.UPDATE,
            state.ConfigureVM,
            vm_manager.UP
        )

    def test_transition_vm_booting(self):
        self._test_transition_hlpr(
            event.UPDATE,
            state.CalcAction,
            vm_manager.BOOTING
        )


class TestStopVMState(BaseTestStateCase):
    state_cls = state.StopVM

    def test_execute(self):
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough'
        )
        self.vm.stop.assert_called_once_with(self.ctx)

    def test_transition_vm_still_up(self):
        self._test_transition_hlpr(event.DELETE, state.StopVM)

    def test_transition_delete_vm_down(self):
        self._test_transition_hlpr(event.DELETE, state.Exit, vm_manager.DOWN)

    def test_transition_restart_vm_down(self):
        self._test_transition_hlpr(event.READ, state.CreateVM, vm_manager.DOWN)


class TestExitState(TestBaseState):
    state_cls = state.Exit


class TestConfigureVMState(BaseTestStateCase):
    state_cls = state.ConfigureVM

    def test_execute_read_configure_success(self):
        self.vm.state = vm_manager.CONFIGURED
        self.assertEqual(self.state.execute(event.READ, self.ctx),
                         event.READ)
        self.vm.configure.assert_called_once_with(self.ctx)

    def test_execute_update_configure_success(self):
        self.vm.state = vm_manager.CONFIGURED
        self.assertEqual(self.state.execute(event.UPDATE, self.ctx),
                         event.POLL)
        self.vm.configure.assert_called_once_with(self.ctx)

    def test_execute_configure_failure(self):
        self.assertEqual(
            self.state.execute(event.CREATE, self.ctx),
            event.CREATE
        )
        self.vm.configure.assert_called_once_with(self.ctx)

    def test_transition_not_configured_down(self):
        self._test_transition_hlpr(event.READ, state.StopVM, vm_manager.DOWN)

    def test_transition_not_configured_restart(self):
        self._test_transition_hlpr(event.READ, state.StopVM,
                                   vm_manager.RESTART)

    def test_transition_not_configured_up(self):
        self._test_transition_hlpr(event.READ, state.PushUpdate,
                                   vm_manager.UP)

    def test_transition_read_configured(self):
        self._test_transition_hlpr(
            event.READ,
            state.ReadStats,
            vm_manager.CONFIGURED
        )

    def test_transition_other_configured(self):
        self._test_transition_hlpr(
            event.POLL,
            state.CalcAction,
            vm_manager.CONFIGURED
        )


class TestReadStatsState(BaseTestStateCase):
    state_cls = state.ReadStats

    def test_execute(self):
        self.vm.read_stats.return_value = 'foo'

        self.assertEqual(
            self.state.execute(event.READ, self.ctx),
            event.POLL
        )
        self.vm.read_stats.assert_called_once_with()
        self.params.bandwidth_callback.assert_called_once_with('foo')

    def test_transition(self):
        self._test_transition_hlpr(event.POLL, state.CalcAction)


class TestAutomaton(unittest.TestCase):
    def setUp(self):
        super(TestAutomaton, self).setUp()

        self.ctx = mock.Mock()  # worker context

        self.vm_mgr_cls = mock.patch('akanda.rug.vm_manager.VmManager').start()
        self.addCleanup(mock.patch.stopall)

        self.delete_callback = mock.Mock()
        self.bandwidth_callback = mock.Mock()

        self.sm = state.Automaton(
            router_id='9306bbd8-f3cc-11e2-bd68-080027e60b25',
            tenant_id='tenant-id',
            delete_callback=self.delete_callback,
            bandwidth_callback=self.bandwidth_callback,
            worker_context=self.ctx,
            queue_warning_threshold=3,
            reboot_error_threshold=5,
        )

    def test_send_message(self):
        message = mock.Mock()
        message.crud = 'update'
        with mock.patch.object(self.sm, 'log') as logger:
            self.sm.send_message(message)
            self.assertEqual(len(self.sm._queue), 1)
            logger.debug.assert_called_with(
                'incoming message brings queue length to %s',
                1,
            )

    def test_send_message_over_threshold(self):
        message = mock.Mock()
        message.crud = 'update'
        for i in range(3):
            self.sm.send_message(message)
        with mock.patch.object(self.sm, 'log') as logger:
            self.sm.send_message(message)
            logger.warning.assert_called_with(
                'incoming message brings queue length to %s',
                4,
            )

    def test_send_message_deleting(self):
        message = mock.Mock()
        message.crud = 'update'
        self.sm.deleted = True
        self.sm.send_message(message)
        self.assertEqual(len(self.sm._queue), 0)
        self.assertFalse(self.sm.has_more_work())

    def test_send_message_in_error(self):
        vm = self.vm_mgr_cls.return_value
        vm.state = state.vm_manager.ERROR
        message = mock.Mock()
        message.crud = 'poll'
        self.sm.send_message(message)
        self.assertEqual(len(self.sm._queue), 0)
        self.assertFalse(self.sm.has_more_work())

        # Non-POLL events should *not* be ignored for routers in ERROR state
        message.crud = 'create'
        with mock.patch.object(self.sm, 'log') as logger:
            self.sm.send_message(message)
            self.assertEqual(len(self.sm._queue), 1)
            logger.debug.assert_called_with(
                'incoming message brings queue length to %s',
                1,
            )

    def test_has_more_work(self):
        with mock.patch.object(self.sm, '_queue') as queue:  # noqa
            self.assertTrue(self.sm.has_more_work())

    def test_has_more_work_deleting(self):
        self.sm.deleted = True
        with mock.patch.object(self.sm, '_queue') as queue:  # noqa
            self.assertFalse(self.sm.has_more_work())

    def test_update_no_work(self):
        with mock.patch.object(self.sm, 'state') as state:
            self.sm.update(self.ctx)
            self.assertFalse(state.called)

    def test_update_exit(self):
        message = mock.Mock()
        message.crud = event.UPDATE
        self.sm.send_message(message)
        self.sm.state = state.Exit(mock.Mock())
        self.sm.update(self.ctx)
        self.delete_callback.called_once_with()

    def test_update_exception_during_excute(self):
        message = mock.Mock()
        message.crud = 'fake'
        self.sm.send_message(message)

        fake_state = mock.Mock()
        fake_state.execute.side_effect = Exception
        fake_state.transition.return_value = state.Exit(mock.Mock())
        self.sm.action = 'fake'
        self.sm.state = fake_state

        with mock.patch.object(self.sm, 'log') as log:
            self.sm.update(self.ctx)

            log.exception.assert_called_once_with(mock.ANY, fake_state, 'fake')

            fake_state.assert_has_calls(
                [
                    mock.call.execute('fake', self.ctx),
                    mock.call.transition('fake', self.ctx)
                ]
            )

    def test_update_calc_action_args(self):
        message = mock.Mock()
        message.crud = event.UPDATE
        self.sm.send_message(message)

        with mock.patch.object(self.sm.state, 'execute',
                               self.ctx) as execute:
            with mock.patch.object(self.sm.state, 'transition',
                                   self.ctx) as transition:
                transition.return_value = state.Exit(mock.Mock())
                self.sm.update(self.ctx)

                execute.called_once_with(
                    event.POLL,
                    self.vm_mgr_cls.return_value,
                    self.ctx,
                    self.sm._queue
                )
                self.delete_callback.called_once_with()

    def test_update_read_stats_args(self):
        message = mock.Mock()
        message.crud = event.READ
        self.sm.send_message(message)

        self.sm.state = state.ReadStats(mock.Mock())
        with mock.patch.object(self.sm.state, 'execute', self.ctx) as execute:
            execute.return_value = state.Exit(mock.Mock())
            self.sm.update(self.ctx)

            execute.called_once_with(
                event.POLL,
                self.vm_mgr_cls.return_value,
                self.ctx,
                self.bandwidth_callback
            )
