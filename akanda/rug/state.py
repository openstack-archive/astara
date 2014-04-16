"""State machine for managing a router.

"""

# See state machine diagram and description:
# https://docs.google.com/a/dreamhost.com/document/d/1Ed5wDqCHW-CUt67ufjOUq4uYj0ECS5PweHxoueUoYUI/edit # noqa

import collections
import itertools
import logging

from akanda.rug.event import POLL, CREATE, READ, UPDATE, DELETE, REBUILD
from akanda.rug import vm_manager


class State(object):

    def __init__(self, log):
        self.log = log

    @property
    def name(self):
        return self.__class__.__name__

    def __str__(self):
        return self.name

    def execute(self, action, vm, worker_context, queue):
        return action

    def transition(self, action, vm, worker_context):
        return self


class CalcAction(State):
    def execute(self, action, vm, worker_context, queue):
        if DELETE in queue:
            self.log.debug('shortcutting to delete')
            return DELETE

        while queue:
            self.log.debug(
                'action = %s, len(queue) = %s, queue = %s',
                action,
                len(queue),
                list(itertools.islice(queue, 0, 60))
            )

            if action == UPDATE and queue[0] == CREATE:
                # upgrade to CREATE from UPDATE by taking the next
                # item from the queue
                self.log.debug('upgrading from update to create')
                action = queue.popleft()
                continue

            elif action == UPDATE and queue[0] == REBUILD:
                # upgrade to REBUILD from UPDATE by taking the next
                # item from the queue
                self.log.debug('upgrading from update to rebuild')
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

        return action

    def transition(self, action, vm, worker_context):
        if vm.state == vm_manager.GONE:
            return StopVM(self.log)
        elif action == DELETE:
            return StopVM(self.log)
        elif action == REBUILD:
            return RebuildVM(self.log)
        elif vm.state == vm_manager.BOOTING:
            return CheckBoot(self.log)
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
    def execute(self, action, vm, worker_context, queue):
        vm.update_state(worker_context)
        return action

    def transition(self, action, vm, worker_context):
        if vm.state == vm_manager.GONE:
            return StopVM(self.log)
        elif vm.state == vm_manager.DOWN:
            return CreateVM(self.log)
        elif action == POLL and vm.state == vm_manager.CONFIGURED:
            return CalcAction(self.log)
        elif action == READ and vm.state == vm_manager.CONFIGURED:
            return ReadStats(self.log)
        else:
            return ConfigureVM(self.log)


class CreateVM(State):
    def execute(self, action, vm, worker_context, queue):
        vm.boot(worker_context)
        return action

    def transition(self, action, vm, worker_context):
        if vm.state == vm_manager.GONE:
            return StopVM(self.log)
        return CheckBoot(self.log)


class CheckBoot(State):
    def execute(self, action, vm, worker_context, queue):
        vm.check_boot(worker_context)
        # Put the action back on the front of the queue so that we can yield
        # and handle it in another state machine traversal (which will proceed
        # from CalcAction directly to CheckBoot).
        if vm.state != vm_manager.GONE:
            queue.appendleft(action)
        return action

    def transition(self, action, vm, worker_context):
        if vm.state == vm_manager.GONE:
            return StopVM(self.log)
        if vm.state == vm_manager.UP:
            return ConfigureVM(self.log)
        return CalcAction(self.log)


class StopVM(State):
    def execute(self, action, vm, worker_context, queue):
        vm.stop(worker_context)
        if vm.state == vm_manager.GONE:
            # Force the action to delete since the router isn't there
            # any more.
            return DELETE
        return action

    def transition(self, action, vm, worker_context):
        if vm.state not in (vm_manager.DOWN, vm_manager.GONE):
            return self
        if vm.state == vm_manager.GONE:
            return Exit(self.log)
        if action == DELETE:
            return Exit(self.log)
        return CreateVM(self.log)


class RebuildVM(State):
    def execute(self, action, vm, worker_context, queue):
        vm.stop(worker_context)
        if vm.state == vm_manager.GONE:
            # Force the action to delete since the router isn't there
            # any more.
            return DELETE
        # Re-create the VM
        return CREATE

    def transition(self, action, vm, worker_context):
        if vm.state not in (vm_manager.DOWN, vm_manager.GONE):
            return self
        if vm.state == vm_manager.GONE:
            return Exit(self.log)
        return CreateVM(self.log)


class Exit(State):
    pass


class ConfigureVM(State):
    def execute(self, action, vm, worker_context, queue):
        vm.configure(worker_context)
        if vm.state == vm_manager.CONFIGURED:
            if action == READ:
                return READ
            else:
                return POLL
        else:
            return action

    def transition(self, action, vm, worker_context):
        if vm.state in (vm_manager.RESTART, vm_manager.DOWN, vm_manager.GONE):
            return StopVM(self.log)
        if vm.state == vm_manager.UP:
            return PushUpdate(self.log)
        # Below here, assume vm.state == vm_manager.CONFIGURED
        if action == READ:
            return ReadStats(self.log)
        return CalcAction(self.log)


class ReadStats(State):
    def execute(self, action, vm, worker_context, queue, bandwidth_callback):
        stats = vm.read_stats()
        bandwidth_callback(stats)
        return POLL

    def transition(self, action, vm, worker_context):
        return CalcAction(self.log)


class Automaton(object):
    def __init__(self, router_id, tenant_id,
                 delete_callback, bandwidth_callback,
                 worker_context):
        """
        :param router_id: UUID of the router being managed
        :type router_id: str
        :param tenant_id: UUID of the tenant being managed
        :type tenant_id: str
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
        self.tenant_id = tenant_id
        self._delete_callback = delete_callback
        self.deleted = False
        self.bandwidth_callback = bandwidth_callback
        self._queue = collections.deque()
        self.log = logging.getLogger(__name__ + '.' + router_id)

        self.state = CalcAction(self.log)
        self.action = POLL
        self.vm = vm_manager.VmManager(router_id, tenant_id, self.log,
                                       worker_context)

    def service_shutdown(self):
        "Called when the parent process is being stopped"

    def _do_delete(self):
        if self._delete_callback is not None:
            self.log.debug('calling delete callback')
            self._delete_callback()
            # Avoid calling the delete callback more than once.
            self._delete_callback = None
        # Remember that this router has been deleted
        self.deleted = True

    def update(self, worker_context):
        "Called when the router config should be changed"
        while self._queue:
            while True:
                if self.deleted:
                    self.log.debug(
                        'skipping update because the router is being deleted'
                    )
                    return

                try:
                    additional_args = ()

                    if isinstance(self.state, ReadStats):
                        additional_args = (self.bandwidth_callback,)

                    self.log.debug('%s.execute(%s) vm.state=%s',
                                   self.state, self.action, self.vm.state)
                    self.action = self.state.execute(
                        self.action,
                        self.vm,
                        worker_context,
                        self._queue,
                        *additional_args
                    )
                    self.log.debug('%s.execute -> %s vm.state=%s',
                                   self.state, self.action, self.vm.state)
                except:
                    self.log.exception(
                        '%s.execute() failed for action: %s',
                        self.state,
                        self.action
                    )

                old_state = self.state
                self.state = self.state.transition(
                    self.action,
                    self.vm,
                    worker_context,
                )
                self.log.debug('%s.transition(%s) -> %s vm.state=%s',
                               old_state, self.action, self.state,
                               self.vm.state)

                # Yield control each time we stop to figure out what
                # to do next.
                if isinstance(self.state, CalcAction):
                    return  # yield

                # We have reached the exit state, so the router has
                # been deleted somehow.
                if isinstance(self.state, Exit):
                    self._do_delete()
                    return

    def send_message(self, message):
        "Called when the worker put a message in the state machine queue"
        if self.deleted:
            # Ignore any more incoming messages
            self.log.debug(
                'deleted state machine, ignoring incoming message %s',
                message)
            return False
        self._queue.append(message.crud)
        self.log.debug(
            'incoming message brings queue length to %s',
            len(self._queue),
        )
        return True

    def has_more_work(self):
        "Called to check if there are more messages in the state machine queue"
        return (not self.deleted) and bool(self._queue)
