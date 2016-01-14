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
# http://akanda.readthedocs.org/en/latest/rug.html#state-machine-workers-and-router-lifecycle

import collections
import itertools

from astara.common.i18n import _LE, _LI, _LW
from astara.event import (POLL, CREATE, READ, UPDATE, DELETE, REBUILD,
                          CLUSTER_REBUILD)
from astara import instance_manager
from astara.drivers import states


class StateParams(object):
    def __init__(self, driver, instance, queue, bandwidth_callback,
                 reboot_error_threshold):
        self.resource = driver
        self.instance = instance
        self.log = driver.log
        self.queue = queue
        self.bandwidth_callback = bandwidth_callback
        self.reboot_error_threshold = reboot_error_threshold
        self.image_uuid = driver.image_uuid


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
    def instance(self):
        return self.params.instance

    @property
    def image_uuid(self):
        return self.params.image_uuid

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
            self.params.resource.log.debug('shortcutting to delete')
            return DELETE

        if (self.params.instance.state == states.DEGRADED and
           CLUSTER_REBUILD not in queue):
            self.params.resource.log.debug(
                'Scheduling a rebuild on degraded cluster')
            queue.append(CLUSTER_REBUILD)

        while queue:
            self.params.resource.log.debug(
                'action = %s, len(queue) = %s, queue = %s',
                action,
                len(queue),
                list(itertools.islice(queue, 0, 60))
            )

            if action == UPDATE and queue[0] == CREATE:
                # upgrade to CREATE from UPDATE by taking the next
                # item from the queue
                self.params.resource.log.debug(
                    'upgrading from update to create')
                action = queue.popleft()
                continue

            elif (action in (CREATE, UPDATE, CLUSTER_REBUILD) and
                  queue[0] == REBUILD):
                # upgrade to REBUILD from CREATE/UPDATE by taking the next
                # item from the queue
                self.params.resource.log.debug('upgrading from %s to rebuild',
                                               action)
                action = queue.popleft()
                continue

            elif action == CREATE and queue[0] == UPDATE:
                # CREATE implies an UPDATE so eat the update event
                # without changing the action
                self.params.resource.log.debug('merging create and update')
                queue.popleft()
                continue

            elif action and queue[0] == POLL:
                # Throw away a poll following any other valid action,
                # because a create or update will automatically handle
                # the poll and repeated polls are not needed.
                self.params.resource.log.debug(
                    'discarding poll event following action %s',
                    action)
                queue.popleft()
                continue

            elif action and action != POLL and action != queue[0]:
                # We are not polling and the next action is something
                # different from what we are doing, so just do the
                # current action.
                self.params.resource.log.debug('done collapsing events')
                break

            self.params.resource.log.debug('popping action from queue')
            action = queue.popleft()

        return action

    def transition(self, action, worker_context):
        if self.instance.state == states.GONE:
            next_action = StopInstance(self.params)
        elif action == DELETE:
            next_action = StopInstance(self.params)
        elif action == REBUILD:
            next_action = RebuildInstance(self.params)
        elif (action == CLUSTER_REBUILD and
              self.instance.state in (states.DEGRADED, states.DOWN)):
            next_action = CreateInstance(self.params)
        elif self.instance.state == states.BOOTING:
            next_action = CheckBoot(self.params)
        elif self.instance.state in (states.DOWN, states.DEGRADED):
            next_action = CreateInstance(self.params)
        else:
            next_action = Alive(self.params)

        if self.instance.state == states.ERROR:
            if action == POLL:
                # If the selected action is to poll, and we are in an
                # error state, then an event slipped through the
                # filter in send_message() and we should ignore it
                # here.
                next_action = self
            elif self.instance.error_cooldown:
                    self.params.resource.log.debug(
                        'Resource is in ERROR cooldown, '
                        'ignoring event.'
                    )
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
    """Remove the error state from the instance.
    """

    def __init__(self, params, next_state=None):
        super(ClearError, self).__init__(params)
        self._next_state = next_state

    def execute(self, action, worker_context):
        # If we are being told explicitly to update the instance, we should
        # ignore any error status.
        self.instance.clear_error(worker_context)
        return action

    def transition(self, action, worker_context):
        if self._next_state:
            return self._next_state
        return CalcAction(self.params)


class Alive(State):
    def execute(self, action, worker_context):
        self.instance.update_state(worker_context)
        return action

    def transition(self, action, worker_context):
        if self.instance.state == states.GONE:
            return StopInstance(self.params)
        elif self.instance.state in (states.DOWN, states.DEGRADED):
            return CreateInstance(self.params)
        elif action == POLL and \
                self.instance.state == states.CONFIGURED:
            return CalcAction(self.params)
        elif action == READ and \
                self.instance.state == states.CONFIGURED:
            return ReadStats(self.params)
        else:
            return ConfigureInstance(self.params)


class CreateInstance(State):
    def execute(self, action, worker_context):
        # Check for a loop where the resource keeps failing to boot or
        # accept the configuration.
        if (not self.instance.state == states.DEGRADED and
           self.instance.attempts >= self.params.reboot_error_threshold):
            self.params.resource.log.info(_LI(
                'Dropping out of boot loop after  %s trials'),
                self.instance.attempts)
            self.instance.set_error(worker_context)
            return action
        self.instance.boot(worker_context)
        self.params.resource.log.debug('CreateInstance attempt %s/%s',
                                       self.instance.attempts,
                                       self.params.reboot_error_threshold)
        return action

    def transition(self, action, worker_context):
        if self.instance.state == states.GONE:
            return StopInstance(self.params)
        elif self.instance.state == states.ERROR:
            return CalcAction(self.params)
        elif self.instance.state == states.DOWN:
            return CreateInstance(self.params)
        return CheckBoot(self.params)


class CheckBoot(State):
    def execute(self, action, worker_context):
        self.instance.update_state(worker_context)
        self.params.resource.log.debug(
            'Instance is %s' % self.instance.state.upper())
        # Put the action back on the front of the queue so that we can yield
        # and handle it in another state machine traversal (which will proceed
        # from CalcAction directly to CheckBoot).
        if self.instance.state not in (states.DOWN,
                                       states.GONE):
            self.queue.appendleft(action)
        return action

    def transition(self, action, worker_context):
        if self.instance.state == states.REPLUG:
            return ReplugInstance(self.params)
        if self.instance.state in (states.DOWN,
                                   states.GONE):
            return StopInstance(self.params)
        if self.instance.state == states.UP:
            return ConfigureInstance(self.params)
        return CalcAction(self.params)


class ReplugInstance(State):
    def execute(self, action, worker_context):
        self.instance.replug(worker_context)
        return action

    def transition(self, action, worker_context):
        if self.instance.state == states.RESTART:
            return StopInstance(self.params)
        return ConfigureInstance(self.params)


class StopInstance(State):
    def execute(self, action, worker_context):
        self.instance.stop(worker_context)
        if self.instance.state == states.GONE:
            # Force the action to delete since the router isn't there
            # any more.
            return DELETE
        return action

    def transition(self, action, worker_context):
        if self.instance.state not in (states.DOWN,
                                       states.GONE):
            return self
        if self.instance.state == states.GONE:
            return Exit(self.params)
        if action == DELETE:
            return Exit(self.params)
        return CreateInstance(self.params)


class RebuildInstance(State):
    def execute(self, action, worker_context):
        self.instance.stop(worker_context)
        if self.instance.state == states.GONE:
            # Force the action to delete since the router isn't there
            # any more.
            return DELETE
        # Re-create the instance
        self.instance.reset_boot_counter()
        return CREATE

    def transition(self, action, worker_context):
        if self.instance.state not in (states.DOWN,
                                       states.GONE):
            return self
        if self.instance.state == states.GONE:
            return Exit(self.params)
        return CreateInstance(self.params)


class Exit(State):
    pass


class ConfigureInstance(State):
    def execute(self, action, worker_context):
        self.instance.configure(worker_context)
        if self.instance.state == states.CONFIGURED:
            if action == READ:
                return READ
            else:
                return POLL
        else:
            return action

    def transition(self, action, worker_context):
        if self.instance.state == states.REPLUG:
            return ReplugInstance(self.params)
        if self.instance.state in (states.RESTART,
                                   states.DOWN,
                                   states.GONE):
            return StopInstance(self.params)
        if self.instance.state == states.UP:
            return PushUpdate(self.params)
        # Below here, assume instance.state == states.CONFIGURED
        if action == READ:
            return ReadStats(self.params)
        return CalcAction(self.params)


class ReadStats(State):
    def execute(self, action, worker_context):
        stats = self.instance.read_stats()
        self.params.bandwidth_callback(stats)
        return POLL

    def transition(self, action, worker_context):
        return CalcAction(self.params)


class Automaton(object):
    def __init__(self, resource, tenant_id,
                 delete_callback, bandwidth_callback,
                 worker_context, queue_warning_threshold,
                 reboot_error_threshold):
        """
        :param resource: An instantiated driver object for the managed resource
        :param tenant_id: UUID of the tenant being managed
        :type tenant_id: str
        :param delete_callback: Invoked when the Automaton decides
                                the router should be deleted.
        :type delete_callback: callable
        :param bandwidth_callback: To be invoked when the Automaton needs to
                                   report how much bandwidth a router has used.
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
        self.resource = resource
        self.tenant_id = tenant_id
        self._delete_callback = delete_callback
        self._queue_warning_threshold = queue_warning_threshold
        self._reboot_error_threshold = reboot_error_threshold
        self.deleted = False
        self.bandwidth_callback = bandwidth_callback
        self._queue = collections.deque()

        self.action = POLL
        self.instance = instance_manager.InstanceManager(self.resource,
                                                         worker_context)
        self._state_params = StateParams(
            self.resource,
            self.instance,
            self._queue,
            self.bandwidth_callback,
            self._reboot_error_threshold,
        )
        self.state = CalcAction(self._state_params)

    @property
    def resource_id(self):
        """Returns the ID of the managed resource"""
        return self.resource.id

    def service_shutdown(self):
        "Called when the parent process is being stopped"

    def _do_delete(self):
        if self._delete_callback is not None:
            self.resource.log.debug('calling delete callback')
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
                    self.resource.log.debug(
                        'skipping update because the router is being deleted'
                    )
                    return

                try:
                    self.resource.log.debug(
                        '%s.execute(%s) instance.state=%s',
                        self.state,
                        self.action,
                        self.instance.state)
                    self.action = self.state.execute(
                        self.action,
                        worker_context,
                    )
                    self.resource.log.debug(
                        '%s.execute -> %s instance.state=%s',
                        self.state,
                        self.action,
                        self.instance.state)
                except:
                    self.resource.log.exception(
                        _LE('%s.execute() failed for action: %s'),
                        self.state,
                        self.action
                    )

                old_state = self.state
                self.state = self.state.transition(
                    self.action,
                    worker_context,
                )
                self.resource.log.debug(
                    '%s.transition(%s) -> %s instance.state=%s',
                    old_state,
                    self.action,
                    self.state,
                    self.instance.state
                )

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
            self.resource.log.debug(
                'deleted state machine, ignoring incoming message %s',
                message)
            return False

        # NOTE(dhellmann): This check is largely redundant with the
        # one in CalcAction.transition() but it may allow us to avoid
        # adding poll events to the queue at all, and therefore cut
        # down on the number of times a worker thread wakes up to
        # process something on a router that isn't going to actually
        # do any work.
        if message.crud == POLL and \
                self.instance.state == states.ERROR:
            self.resource.log.info(_LI(
                'Resource status is ERROR, ignoring POLL message: %s'),
                message,
            )
            return False

        if message.crud == REBUILD:
            if message.body.get('image_uuid'):
                self.resource.log.info(_LI(
                    'Resource is being REBUILT with custom image %s'),
                    message.body['image_uuid']
                )
                self.image_uuid = message.body['image_uuid']
            else:
                self.image_uuid = self.resource.image_uuid

        self._queue.append(message.crud)
        queue_len = len(self._queue)
        if queue_len > self._queue_warning_threshold:
            logger = self.resource.log.warning
        else:
            logger = self.resource.log.debug
        logger(_LW('incoming message brings queue length to %s'), queue_len)
        return True

    @property
    def image_uuid(self):
        return self.state.params.image_uuid

    @image_uuid.setter
    def image_uuid(self, value):
        self.state.params.image_uuid = value

    def has_more_work(self):
        "Called to check if there are more messages in the state machine queue"
        return (not self.deleted) and bool(self._queue)

    def has_error(self):
        return self.instance.state == states.ERROR

    def drop_queue(self):
        """Drop all pending actions from the local state machine's work queue.

        This is used after a ring rebalance if this state machine no longer
        maps to the local Rug process.
        """
        self.resource.log.info(
            'Dropping %s pending actions from queue', len(self._queue))
        self._queue.clear()
