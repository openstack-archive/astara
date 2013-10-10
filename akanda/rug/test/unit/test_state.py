import collections

import mock
import unittest2 as unittest

from akanda.rug import event
from akanda.rug import state
from akanda.rug import vm_manager


class BaseTestStateCase(unittest.TestCase):
    state_cls = state.State

    def setUp(self):
        self.state = self.state_cls(mock.Mock())
        vm_mgr_cls = mock.patch('akanda.rug.vm_manager.VmManager').start()
        self.addCleanup(mock.patch.stopall)
        self.vm = vm_mgr_cls.return_value

    def _test_transition_hlpr(self, action, expected_class,
                              vm_state=state.vm_manager.UP):
        self.vm.state = vm_state
        self.assertIsInstance(
            self.state.transition(action, self.vm),
            expected_class
        )


class TestBaseState(BaseTestStateCase):
    def test_execute(self):
        self.assertEqual(
            self.state.execute('action', self.vm),
            'action'
        )

    def test_transition(self):
        self.assertEqual(
            self.state.transition('action', self.vm),
            self.state
        )


class TestCalcActionState(BaseTestStateCase):
    state_cls = state.CalcAction

    def _test_hlpr(self, expected_action, queue_states,
                   leftover=0, initial_action=event.POLL):
        queue = collections.deque(queue_states)
        self.assertEqual(
            self.state.execute(initial_action, self.vm, queue),
            expected_action
        )
        self.assertEqual(len(queue), leftover)

    def test_execute_empty_queue(self):
        self._test_hlpr('testaction', [], initial_action='testaction')

    def test_execute_delete_in_queue(self):
        self._test_hlpr(event.DELETE, [event.CREATE, event.DELETE], 2)

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

    def test_transition_delete_down_vm(self):
        self._test_transition_hlpr(event.DELETE, state.Exit, vm_manager.DOWN)

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
            state.Wait,
            vm_manager.CONFIGURED
        )

    def test_transition_other_up_vm(self):
        for evt in [event.READ, event.UPDATE, event.CREATE]:
            self._test_transition_hlpr(evt, state.Alive)


class TestAliveState(BaseTestStateCase):
    state_cls = state.Alive

    def test_execute(self):
        self.assertEqual(
            self.state.execute('passthrough', self.vm),
            'passthrough'
        )
        self.vm.update_state.assert_called_once_with()

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
        self.assertEqual(
            self.state.execute('passthrough', self.vm),
            'passthrough'
        )
        self.vm.boot.assert_called_once_with()

    def test_transition_vm_down(self):
        self._test_transition_hlpr(
            event.READ,
            state.CalcAction,
            vm_manager.DOWN
        )

    def test_transition_vm_up(self):
        self._test_transition_hlpr(event.READ, state.ConfigureVM)


class TestStopVMState(BaseTestStateCase):
    state_cls = state.StopVM

    def test_execute(self):
        self.assertEqual(
            self.state.execute('passthrough', self.vm),
            'passthrough'
        )
        self.vm.stop.assert_called_once_with()

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
        self.assertEqual(self.state.execute(event.READ, self.vm), event.READ)
        self.vm.configure.assert_called_once_with()

    def test_execute_update_configure_success(self):
        self.vm.state = vm_manager.CONFIGURED
        self.assertEqual(self.state.execute(event.UPDATE, self.vm), event.POLL)
        self.vm.configure.assert_called_once_with()

    def test_execute_configure_failure(self):
        self.assertEqual(
            self.state.execute(event.CREATE, self.vm),
            event.CREATE
        )
        self.vm.configure.assert_called_once_with()

    def test_transition_not_configured(self):
        self._test_transition_hlpr(event.READ, state.StopVM, vm_manager.DOWN)

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

        callback = mock.Mock()

        self.assertEqual(
            self.state.execute(event.READ, self.vm, callback),
            event.POLL
        )
        self.vm.read_stats.assert_called_once_with()
        callback.assert_called_once_with('foo')

    def test_transition(self):
        self._test_transition_hlpr(event.POLL, state.CalcAction)


class TestWaitState(BaseTestStateCase):
    state_cls = state.Wait

    def test_execute(self):
        with mock.patch('time.sleep') as sleep:
            self.assertEqual(
                self.state.execute(event.POLL, self.vm),
                event.POLL
            )
            sleep.assert_called_once_with(mock.ANY)

    def test_transition(self):
        self._test_transition_hlpr(event.POLL, state.CalcAction)


class TestAutomaton(unittest.TestCase):
    def setUp(self):
        super(TestAutomaton, self).setUp()

        self.vm_mgr_cls = mock.patch('akanda.rug.vm_manager.VmManager').start()
        self.addCleanup(mock.patch.stopall)

        self.delete_callback = mock.Mock()
        self.bandwidth_callback = mock.Mock()

        self.sm = state.Automaton(
            router_id='9306bbd8-f3cc-11e2-bd68-080027e60b25',
            delete_callback=self.delete_callback,
            bandwidth_callback=self.bandwidth_callback
        )

    def test_send_message(self):
        message = mock.Mock()
        message.crud = 'update'
        self.sm.send_message(message)
        self.assertEqual(len(self.sm._queue), 1)

    def test_has_more_work(self):
        with mock.patch.object(self.sm, '_queue') as queue:  # noqa
            self.assertTrue(self.sm.has_more_work())

    def test_update_no_work(self):
        with mock.patch.object(self.sm, 'state') as state:
            self.sm.update()
            self.assertFalse(state.called)

    def test_update_exit(self):
        message = mock.Mock()
        message.crud = event.UPDATE
        self.sm.send_message(message)
        self.sm.state = state.Exit(mock.Mock())

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
            self.sm.update()

            log.exception.assert_called_once_with(mock.ANY, 'fake')

            fake_state.assert_has_calls(
                [
                    mock.call.execute('fake', self.vm_mgr_cls.return_value),
                    mock.call.transition('fake', self.vm_mgr_cls.return_value)
                ]
            )

    def test_update_calc_action_args(self):
        message = mock.Mock()
        message.crud = event.UPDATE
        self.sm.send_message(message)

        with mock.patch.object(self.sm.state, 'execute') as execute:
            with mock.patch.object(self.sm.state, 'transition') as transition:
                transition.return_value = state.Exit(mock.Mock())
                self.sm.update()

                execute.called_once_with(
                    event.POLL,
                    self.vm_mgr_cls.return_value,
                    self.sm._queue
                )
                self.delete_callback.called_once_with()

    def test_update_read_stats_args(self):
        message = mock.Mock()
        message.crud = event.READ
        self.sm.send_message(message)

        self.sm.state = state.ReadStats(mock.Mock())
        with mock.patch.object(self.sm.state, 'execute') as execute:
            execute.return_value = state.Exit(mock.Mock())
            self.sm.update()

            execute.called_once_with(
                event.POLL,
                self.vm_mgr_cls.return_value,
                self.bandwidth_callback
            )
