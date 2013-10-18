"""State machine for managing a router.
"""

import collections
import logging
import time

from akanda.rug.event import POLL, CREATE, READ, UPDATE, DELETE
from akanda.rug import vm_manager

WAIT_PERIOD = 10


class State(object):

    def __init__(self, log):
        self.log = log

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
                return Exit(self.log)
            else:
                return StopVM(self.log)
        elif vm.state == vm_manager.DOWN:
            return CreateVM(self.log)
        elif action == POLL and vm.state == vm_manager.CONFIGURED:
            return Wait(self.log)
        else:
            return Alive(self.log)


class Alive(State):
    def execute(self, action, vm):
        vm.update_state()
        return action

    def transition(self, action, vm):
        if vm.state == vm_manager.DOWN:
            return CreateVM(self.log)
        elif action == POLL and vm.state == vm_manager.CONFIGURED:
            return CalcAction(self.log)
        elif action == READ and vm.state == vm_manager.CONFIGURED:
            return ReadStats(self.log)
        else:
            return ConfigureVM(self.log)


class CreateVM(State):
    def execute(self, action, vm):
        vm.boot()
        return action

    def transition(self, action, vm):
        if vm.state == vm_manager.UP:
            return ConfigureVM(self.log)
        else:
            return CalcAction(self.log)


class StopVM(State):
    def execute(self, action, vm):
        vm.stop()
        return action

    def transition(self, action, vm):
        if vm.state != vm_manager.DOWN:
            return self
        if action == DELETE:
            return Exit(self.log)
        else:
            return CreateVM(self.log)


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
            return StopVM(self.log)
        elif action == READ:
            return ReadStats(self.log)
        else:
            return CalcAction(self.log)


class ReadStats(State):
    def execute(self, action, vm, bandwidth_callback):
        stats = vm.read_stats()
        bandwidth_callback(stats)
        return POLL

    def transition(self, action, vm):
        return CalcAction(self.log)


class Wait(State):
    def execute(self, action, vm):
        time.sleep(WAIT_PERIOD)
        return action

    def transition(self, action, vm):
        return CalcAction(self.log)


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
        self._delete_callback = delete_callback
        self.bandwidth_callback = bandwidth_callback
        self._queue = collections.deque()
        self.log = logging.getLogger(__name__ + '.' + router_id)

        self.state = CalcAction(self.log)
        self.action = POLL
        self.vm = vm_manager.VmManager(router_id, self.log)

    @property
    def _deleting(self):
        """Boolean property indicating whether this state machine is stopping.
        """
        return isinstance(self.state, Exit)

    def service_shutdown(self):
        "Called when the parent process is being stopped"

    def _do_delete(self):
        if self._delete_callback is not None:
            self._delete_callback()
            # Avoid calling the delete callback more than once.
            self._delete_callback = None

    def update(self):
        "Called when the router config should be changed"
        while self._queue:
            while True:
                if self._deleting:
                    self._do_delete()
                    return

                try:
                    additional_args = ()

                    if isinstance(self.state, CalcAction):
                        additional_args = (self._queue,)
                    elif isinstance(self.state, ReadStats):
                        additional_args = (self.bandwidth_callback,)

                    self.log.debug('executing %r for %r %s',
                                   self.action, self.vm, self)
                    self.action = self.state.execute(
                        self.action,
                        self.vm,
                        *additional_args
                        )
                    self.log.debug('execute for %r returned next action %r',
                                   self.vm, self.action)
                except:
                    self.log.exception(
                        'execute() failed for action: %s',
                        self.action
                    )

                old_state = self.state
                self.state = self.state.transition(self.action, self.vm)
                self.log.debug('%s transitioned from %s to %s',
                               self.vm, old_state, self.state)

                if isinstance(self.state, CalcAction):
                    return  # yield

    def send_message(self, message):
        "Called when the worker put a message in the state machine queue"
        self.log.debug('Message: %s -- deleting method % s', message,
                       self._deleting)
        if self._deleting:
            # Ignore any more incoming messages
            self.log.debug(
                'deleting state machine, ignoring incoming message %s',
                message)
            return
        self._queue.append(message.crud)

    def has_more_work(self):
        "Called to check if there are more messages in the state machine queue"
        return (not self._deleting) and bool(self._queue)
