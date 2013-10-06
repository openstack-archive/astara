"""State machine for managing a router.
"""

import collections
import logging
import time

from akanda.rug.event import POLL, CREATE, READ, UPDATE, DELETE
from akanda.rug import vm_manager

WAIT_PERIOD = 10


class State(object):
    def execute(self, action, vm):
        return action

    def transition(self, action, vm):
        return self


class CalcAction(State):
    def execute(self, action, vm, queue):
        if DELETE in queue:
            return DELETE

        while queue:
            if action == UPDATE and queue[0] == CREATE:
                # upgrade to CREATE from UPDATE
                pass
            elif action == CREATE and queue[0] == UPDATE:
                # CREATE implies an UPDATE so eat the event
                queue.popleft()
                continue
            elif queue[0] == POLL:
                pass  # a no-op when collapsing events
            elif action != POLL and action != queue[0]:
                break
            action = queue.popleft()
        return action

    def transition(self, action, vm):
        if action == DELETE:
            if vm.state == vm_manager.DOWN:
                return Exit()
            else:
                return StopVM()
        elif vm.state == vm_manager.DOWN:
            return CreateVM()
        elif action == POLL and vm.state == vm_manager.CONFIGURED:
            return Wait()
        else:
            return Alive()


class Alive(State):
    def execute(self, action, vm):
        vm.update_state()
        return action

    def transition(self, action, vm):
        if vm.state == vm_manager.DOWN:
            return CreateVM()
        elif action == POLL and vm.state == vm_manager.CONFIGURED:
            return CalcAction()
        elif action == READ and vm.state == vm_manager.CONFIGURED:
            return ReadStats()
        else:
            return ConfigureVM()


class CreateVM(State):
    def execute(self, action, vm):
        vm.boot()
        return action

    def transition(self, action, vm):
        if vm.state == vm_manager.UP:
            return ConfigureVM()
        else:
            return CalcAction()


class StopVM(State):
    def execute(self, action, vm):
        vm.stop()
        return action

    def transition(self, action, vm):
        if vm.state != vm_manager.DOWN:
            return self
        if action == DELETE:
            return Exit()
        else:
            return CreateVM()


class Exit(State):
    pass


class ConfigureVM(State):
    def execute(self, action, vm):
        vm.configure()
        if vm.state == vm_manager.CONFIGURED:
            if action == READ:
                return READ
            else:
                return POLL
        else:
            return action

    def transition(self, action, vm):
        if vm.state != vm_manager.CONFIGURED:
            return StopVM()
        elif action == READ:
            return ReadStats()
        else:
            return CalcAction()


class ReadStats(State):
    def execute(self, action, vm, bandwidth_callback):
        stats = vm.read_stats()
        bandwidth_callback(stats)
        return POLL

    def transition(self, action, vm):
        return CalcAction()


class Wait(State):
    def execute(self, action, vm):
        time.sleep(WAIT_PERIOD)
        return action

    def transition(self, action, vm):
        return CalcAction()


class Automaton(object):
    def __init__(self, router_id, delete_callback, bandwidth_callback):
        """
        :param router_id: UUID of the router being managed
        :type router_id: str
        :param delete_callback: Invoked when the Automaton decides
                                the router should be deleted.
        :type delete_callback: callable
        :param bandwidth_callback: To be invoked when the Automaton
                                   needs to report how much bandwidth
                                   a router has used.
        :type bandwidth_callback: callable taking router_id and bandwidth
                                  info dict
        """
        self.router_id = router_id
        self.delete_callback = delete_callback
        self.bandwidth_callback = bandwidth_callback
        self._queue = collections.deque()
        self.log = logging.getLogger(__name__ + '.' + router_id)

        self.state = CalcAction()
        self.action = POLL
        self.vm = vm_manager.VmManager(router_id, self.log)

    def service_shutdown(self):
        "Called when the parent process is being stopped"

    def update(self):
        "Called when the router config should be changed"
        while self._queue:
            while True:
                if isinstance(self.state, Exit):
                    self.delete_callback()
                    return

                try:
                    additional_args = ()

                    if isinstance(self.state, CalcAction):
                        additional_args = (self._queue,)
                    elif isinstance(self.state, ReadStats):
                        additional_args = (self.bandwidth_callback,)

                    self.action = self.state.execute(
                        self.action,
                        self.vm,
                        *additional_args
                        )
                except:
                    self.log.exception(
                        'execute() failed for action: %s',
                        self.action
                    )

                self.state = self.state.transition(self.action, self.vm)

                if isinstance(self.state, CalcAction):
                    return  # yield

    def send_message(self, message):
        "Called when the worker put a message in the state machine queue"
        self._queue.append(message.crud)

    def has_more_work(self):
        "Called to check if there are more messages in the state machine queue"
        return bool(self._queue)
