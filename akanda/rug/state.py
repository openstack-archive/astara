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


"""State machine for managing a router.

"""

# See state machine diagram and description:
# https://docs.google.com/a/dreamhost.com/document/d/1Ed5wDqCHW-CUt67ufjOUq4uYj0ECS5PweHxoueUoYUI/edit # noqa

import collections
import itertools
import logging

from oslo_config import cfg

from akanda.rug.event import POLL, CREATE, READ, UPDATE, DELETE, REBUILD
from akanda.rug import vm_manager


class StateParams(object):
    def __init__(self, vm, log, queue, bandwidth_callback,
                 reboot_error_threshold, router_image_uuid):
        self.vm = vm
        self.log = log
        self.queue = queue
        self.bandwidth_callback = bandwidth_callback
        self.reboot_error_threshold = reboot_error_threshold
        self.router_image_uuid = router_image_uuid


class State(object):

    def __init__(self, params):
        self.params = params

    @property
    def log(self):
        return self.params.log

    @property
    def queue(self):
        return self.params.queue

    @property
    def vm(self):
        return self.params.vm

    @property
    def router_image_uuid(self):
        return self.params.router_image_uuid

    @property
    def name(self):
        return self.__class__.__name__

    def __str__(self):
        return self.name

    def execute(self, action, worker_context):
        return action

    def transition(self, action, worker_context):
        return self


class CalcAction(State):
    def execute(self, action, worker_context):
        queue = self.queue
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

            elif action in (CREATE, UPDATE) and queue[0] == REBUILD:
                # upgrade to REBUILD from CREATE/UPDATE by taking the next
                # item from the queue
                self.log.debug('upgrading from %s to rebuild' % action)
                action = queue.popleft()
                continue

            elif action == CREATE and queue[0] == UPDATE:
                # CREATE implies an UPDATE so eat the update event
                # without changing the action
                self.log.debug('merging create and update')
                queue.popleft()
                continue

            elif action and queue[0] == POLL:
                # Throw away a poll following any other valid action,
                # because a create or update will automatically handle
                # the poll and repeated polls are not needed.
                self.log.debug('discarding poll event following action %s',
                               action)
                queue.popleft()
                continue

            elif action and action != POLL and action != queue[0]:
                # We are not polling and the next action is something
                # different from what we are doing, so just do the
                # current action.
                self.log.debug('done collapsing events')
                break

            self.log.debug('popping action from queue')
            action = queue.popleft()

        return action

    def transition(self, action, worker_context):
        if self.vm.state == vm_manager.GONE:
            next_action = StopVM(self.params)
        elif action == DELETE:
            next_action = StopVM(self.params)
        elif action == REBUILD:
            next_action = RebuildVM(self.params)
        elif self.vm.state == vm_manager.BOOTING:
            next_action = CheckBoot(self.params)
        elif self.vm.state == vm_manager.DOWN:
            next_action = CreateVM(self.params)
        else:
            next_action = Alive(self.params)
        if self.vm.state == vm_manager.ERROR:
            if action == POLL:
                # If the selected action is to poll, and we are in an
                # error state, then an event slipped through the
                # filter in send_message() and we should ignore it
                # here.
                next_action = self
            elif self.vm.error_cooldown:
                    self.log.debug('Router is in ERROR cooldown, ignoring '
                                   'event.')
                    next_action = self
            else:
                # If this isn't a POLL, and the configured `error_cooldown`
                # has passed, clear the error status before doing what we
                # really want to do.
                next_action = ClearError(self.params, next_action)
        return next_action


class PushUpdate(State):
    """Put an update instruction on the queue for the state machine.
    """
    def execute(self, action, worker_context):
        # Put the action back on the front of the queue.
        self.queue.appendleft(UPDATE)
        return action

    def transition(self, action, worker_context):
        return CalcAction(self.params)


class ClearError(State):
    """Remove the error state from the VM.
    """

    def __init__(self, params, next_state=None):
        super(ClearError, self).__init__(params)
        self._next_state = next_state

    def execute(self, action, worker_context):
        # If we are being told explicitly to update the VM, we should
        # ignore any error status.
        self.vm.clear_error(worker_context)
        return action

    def transition(self, action, worker_context):
        if self._next_state:
            return self._next_state
        return CalcAction(self.params)


class Alive(State):
    def execute(self, action, worker_context):
        self.vm.update_state(worker_context)
        return action

    def transition(self, action, worker_context):
        if self.vm.state == vm_manager.GONE:
            return StopVM(self.params)
        elif self.vm.state == vm_manager.DOWN:
            return CreateVM(self.params)
        elif action == POLL and self.vm.state == vm_manager.CONFIGURED:
            return CalcAction(self.params)
        elif action == READ and self.vm.state == vm_manager.CONFIGURED:
            return ReadStats(self.params)
        else:
            return ConfigureVM(self.params)


class CreateVM(State):
    def execute(self, action, worker_context):
        # Check for a loop where the router keeps failing to boot or
        # accept the configuration.
        if self.vm.attempts >= self.params.reboot_error_threshold:
            self.log.info('dropping out of boot loop after %s trials',
                          self.vm.attempts)
            self.vm.set_error(worker_context)
            return action
        self.vm.boot(worker_context, self.router_image_uuid)
        self.log.debug('CreateVM attempt %s/%s',
                       self.vm.attempts,
                       self.params.reboot_error_threshold)
        return action

    def transition(self, action, worker_context):
        if self.vm.state == vm_manager.GONE:
            return StopVM(self.params)
        elif self.vm.state == vm_manager.ERROR:
            return CalcAction(self.params)
        elif self.vm.state == vm_manager.DOWN:
            return CreateVM(self.params)
        return CheckBoot(self.params)


class CheckBoot(State):
    def execute(self, action, worker_context):
        self.vm.check_boot(worker_context)
        # Put the action back on the front of the queue so that we can yield
        # and handle it in another state machine traversal (which will proceed
        # from CalcAction directly to CheckBoot).
        if self.vm.state not in (vm_manager.DOWN, vm_manager.GONE):
            self.queue.appendleft(action)
        return action

    def transition(self, action, worker_context):
        if self.vm.state in (vm_manager.DOWN,
                             vm_manager.GONE):
            return StopVM(self.params)
        if self.vm.state == vm_manager.UP:
            return ConfigureVM(self.params)
        return CalcAction(self.params)


class ReplugVM(State):
    def execute(self, action, worker_context):
        self.vm.replug(worker_context)
        return action

    def transition(self, action, worker_context):
        if self.vm.state == vm_manager.RESTART:
            return StopVM(self.params)
        return ConfigureVM(self.params)


class StopVM(State):
    def execute(self, action, worker_context):
        self.vm.stop(worker_context)
        if self.vm.state == vm_manager.GONE:
            # Force the action to delete since the router isn't there
            # any more.
            return DELETE
        return action

    def transition(self, action, worker_context):
        if self.vm.state not in (vm_manager.DOWN, vm_manager.GONE):
            return self
        if self.vm.state == vm_manager.GONE:
            return Exit(self.params)
        if action == DELETE:
            return Exit(self.params)
        return CreateVM(self.params)


class RebuildVM(State):
    def execute(self, action, worker_context):
        self.vm.stop(worker_context)
        if self.vm.state == vm_manager.GONE:
            # Force the action to delete since the router isn't there
            # any more.
            return DELETE
        # Re-create the VM
        self.vm.reset_boot_counter()
        return CREATE

    def transition(self, action, worker_context):
        if self.vm.state not in (vm_manager.DOWN, vm_manager.GONE):
            return self
        if self.vm.state == vm_manager.GONE:
            return Exit(self.params)
        return CreateVM(self.params)


class Exit(State):
    pass


class ConfigureVM(State):
    def execute(self, action, worker_context):
        self.vm.configure(worker_context)
        if self.vm.state == vm_manager.CONFIGURED:
            if action == READ:
                return READ
            else:
                return POLL
        else:
            return action

    def transition(self, action, worker_context):
        if self.vm.state == vm_manager.REPLUG:
            return ReplugVM(self.params)
        if self.vm.state in (vm_manager.RESTART,
                             vm_manager.DOWN,
                             vm_manager.GONE):
            return StopVM(self.params)
        if self.vm.state == vm_manager.UP:
            return PushUpdate(self.params)
        # Below here, assume vm.state == vm_manager.CONFIGURED
        if action == READ:
            return ReadStats(self.params)
        return CalcAction(self.params)


class ReadStats(State):
    def execute(self, action, worker_context):
        stats = self.vm.read_stats()
        self.params.bandwidth_callback(stats)
        return POLL

    def transition(self, action, worker_context):
        return CalcAction(self.params)


class Automaton(object):
    def __init__(self, router_id, tenant_id,
                 delete_callback, bandwidth_callback,
                 worker_context, queue_warning_threshold,
                 reboot_error_threshold):
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
        :param queue_warning_threshold: Limit after which adding items
                                        to the queue triggers a warning.
        :type queue_warning_threshold: int
        :param reboot_error_threshold: Limit after which trying to reboot
                                       the router puts it into an error state.
        :type reboot_error_threshold: int
        """
        self.router_id = router_id
        self.tenant_id = tenant_id
        self._delete_callback = delete_callback
        self._queue_warning_threshold = queue_warning_threshold
        self._reboot_error_threshold = reboot_error_threshold
        self.deleted = False
        self.bandwidth_callback = bandwidth_callback
        self._queue = collections.deque()
        self.log = logging.getLogger(__name__ + '.' + router_id)

        self.action = POLL
        self.vm = vm_manager.VmManager(router_id, tenant_id, self.log,
                                       worker_context)
        self._state_params = StateParams(
            self.vm,
            self.log,
            self._queue,
            self.bandwidth_callback,
            self._reboot_error_threshold,
            cfg.CONF.router_image_uuid
        )
        self.state = CalcAction(self._state_params)

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
                    self.log.debug('%s.execute(%s) vm.state=%s',
                                   self.state, self.action, self.vm.state)
                    self.action = self.state.execute(
                        self.action,
                        worker_context,
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

        # NOTE(dhellmann): This check is largely redundant with the
        # one in CalcAction.transition() but it may allow us to avoid
        # adding poll events to the queue at all, and therefore cut
        # down on the number of times a worker thread wakes up to
        # process something on a router that isn't going to actually
        # do any work.
        if message.crud == POLL and self.vm.state == vm_manager.ERROR:
            self.log.info(
                'Router status is ERROR, ignoring POLL message: %s',
                message,
            )
            return False

        if message.crud == REBUILD:
            if message.body.get('router_image_uuid'):
                self.log.info(
                    'Router is being REBUILT with custom image %s',
                    message.body['router_image_uuid']
                )
                self.router_image_uuid = message.body['router_image_uuid']
            else:
                self.router_image_uuid = cfg.CONF.router_image_uuid

        self._queue.append(message.crud)
        queue_len = len(self._queue)
        if queue_len > self._queue_warning_threshold:
            logger = self.log.warning
        else:
            logger = self.log.debug
        logger('incoming message brings queue length to %s', queue_len)
        return True

    @property
    def router_image_uuid(self):
        return self.state.params.router_image_uuid

    @router_image_uuid.setter
    def router_image_uuid(self, value):
        self.state.params.router_image_uuid = value

    def has_more_work(self):
        "Called to check if there are more messages in the state machine queue"
        return (not self.deleted) and bool(self._queue)

    def has_error(self):
        return self.vm.state == vm_manager.ERROR
