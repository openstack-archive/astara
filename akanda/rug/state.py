"""State machine for managing a router.

"""

# See state machine diagram and description:
# https://docs.google.com/a/dreamhost.com/document/d/1Ed5wDqCHW-CUt67ufjOUq4uYj0ECS5PweHxoueUoYUI/edit # noqa

import collections
import logging

from akanda.rug.event import POLL, CREATE, READ, UPDATE, DELETE
from akanda.rug import vm_manager


class State(object):

    def __init__(self, log):
        self.log = log

    @property
    def name(self):
        return self.__class__.__name__

    def __str__(self):
        return self.name

    def execute(self, action, vm, worker_context):
        return action

    def transition(self, action, vm, worker_context):
        return self


class CalcAction(State):
    def execute(self, action, vm, worker_context, queue):
        if DELETE in queue:
            return DELETE

        while queue:
            self.log.debug('action = %s, queue = %s', action, queue)

            if action == UPDATE and queue[0] == CREATE:
                # upgrade to CREATE from UPDATE by taking the next
                # item from the queue
                self.log.debug('upgrading from update to create')
                action = queue.popleft()
                continue

            elif action == CREATE and queue[0] == UPDATE:
                # CREATE implies an UPDATE so eat the update event
                # without changing the action
                self.log.debug('merging create and update')
                queue.popleft()
                continue

            elif queue[0] == POLL:
                # Throw away a poll following any other action,
                # because a create or update will automatically handle
                # the poll and repeated polls are not needed.
                self.log.debug('discarding poll event following action %s',
                               action)
                queue.popleft()
                continue

            elif action != POLL and action != queue[0]:
                # We are not polling and the next action is something
                # different from what we are doing, so just do the
                # current action.
                self.log.debug('done collapsing events')
                break

            self.log.debug('popping action from queue')
            action = queue.popleft()

        self.log.debug('CalcAction -> %s', action)
        return action

    def transition(self, action, vm, worker_context):
        if action == DELETE:
            if vm.state == vm_manager.DOWN:
                return Exit(self.log)
            else:
                return StopVM(self.log)
        elif vm.state == vm_manager.DOWN:
            return CreateVM(self.log)
        else:
            return Alive(self.log)


class PushUpdate(State):
    """Put an update instruction on the queue for the state machine.
    """
    def execute(self, action, vm, worker_context, queue):
        # Put the action back on the front of the queue.
        queue.appendleft(UPDATE)

    def transition(self, action, vm, worker_context):
        return CalcAction(self.log)


class Alive(State):
    def execute(self, action, vm, worker_context):
        vm.update_state(worker_context)
        return action

    def transition(self, action, vm, worker_context):
        if vm.state == vm_manager.DOWN:
            return CreateVM(self.log)
        elif action == POLL and vm.state == vm_manager.CONFIGURED:
            return CalcAction(self.log)
        elif action == READ and vm.state == vm_manager.CONFIGURED:
            return ReadStats(self.log)
        else:
            return ConfigureVM(self.log)


class CreateVM(State):
    def execute(self, action, vm, worker_context):
        vm.boot(worker_context)
        return action

    def transition(self, action, vm, worker_context):
        if vm.state == vm_manager.UP:
            return ConfigureVM(self.log)
        else:
            return CalcAction(self.log)


class StopVM(State):
    def execute(self, action, vm, worker_context):
        vm.stop(worker_context)
        return action

    def transition(self, action, vm, worker_context):
        if vm.state != vm_manager.DOWN:
            return self
        if action == DELETE:
            return Exit(self.log)
        else:
            return CreateVM(self.log)


class Exit(State):
    pass


class ConfigureVM(State):
    def execute(self, action, vm, worker_context):
        vm.configure(worker_context)
        if vm.state == vm_manager.CONFIGURED:
            if action == READ:
                return READ
            else:
                return POLL
        else:
            return action

    def transition(self, action, vm, worker_context):
        if vm.state in (vm_manager.RESTART, vm_manager.DOWN):
            return StopVM(self.log)
        if vm.state == vm_manager.UP:
            return PushUpdate(self.log)
        # Below here, assume vm.state == vm_manager.CONFIGURED
        if action == READ:
            return ReadStats(self.log)
        return CalcAction(self.log)


class ReadStats(State):
    def execute(self, action, vm, worker_context, bandwidth_callback):
        stats = vm.read_stats()
        bandwidth_callback(stats)
        return POLL

    def transition(self, action, vm, worker_context):
        return CalcAction(self.log)


class Automaton(object):
    def __init__(self, router_id, delete_callback, bandwidth_callback,
                 worker_context):
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
        :param worker_context: a WorkerContext
        :type worker_context: WorkerContext
        """
        self.router_id = router_id
        self._delete_callback = delete_callback
        self.bandwidth_callback = bandwidth_callback
        self._queue = collections.deque()
        self.log = logging.getLogger(__name__ + '.' + router_id)

        self.state = CalcAction(self.log)
        self.action = POLL
        self.vm = vm_manager.VmManager(router_id, self.log, worker_context)

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

    def update(self, worker_context):
        "Called when the router config should be changed"
        while self._queue:
            while True:
                if self._deleting:
                    self.log.debug(
                        'skipping update because the router is being deleted'
                    )
                    self._do_delete()
                    return

                try:
                    additional_args = ()

                    if isinstance(self.state, (CalcAction, PushUpdate)):
                        additional_args = (self._queue,)
                    elif isinstance(self.state, ReadStats):
                        additional_args = (self.bandwidth_callback,)

                    self.log.debug('execute(%s)', self.action)
                    self.action = self.state.execute(
                        self.action,
                        self.vm,
                        worker_context,
                        *additional_args
                    )
                    self.log.debug('execute -> %s', self.action)
                except:
                    self.log.exception(
                        'execute() failed for action: %s',
                        self.action
                    )

                old_state = self.state
                self.state = self.state.transition(
                    self.action,
                    self.vm,
                    worker_context,
                )
                self.log.debug('state %s -> %s', old_state, self.state)

                if isinstance(self.state, CalcAction):
                    return  # yield

    def send_message(self, message):
        "Called when the worker put a message in the state machine queue"
        if self._deleting:
            # Ignore any more incoming messages
            self.log.debug(
                'deleting state machine, ignoring incoming message %s',
                message)
            return
        self._queue.append(message.crud)
        self.log.debug(
            'incoming message brings queue length to %s',
            len(self._queue),
        )

    def has_more_work(self):
        "Called to check if there are more messages in the state machine queue"
        return (not self._deleting) and bool(self._queue)
