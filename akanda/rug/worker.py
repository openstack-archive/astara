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


"""Worker process parts.
"""

import collections
import Queue
import threading
import uuid

from logging import INFO

from oslo_config import cfg
from oslo_log import log as logging

from akanda.rug import commands
from akanda.rug import event
from akanda.rug import tenant
from akanda.rug.api import nova
from akanda.rug.api import neutron
from akanda.rug.db import api as db_api

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

WORKER_OPTS = [
    cfg.StrOpt(
        'ignored_router_directory',
        default='/etc/akanda-rug/ignored',
        help='Directory to scan for routers to ignore for debugging',
    ),
    cfg.IntOpt(
        'queue_warning_threshold',
        default=100,
        help='warn if the event backlog for a tenant exceeds this value',
    ),
    cfg.IntOpt(
        'reboot_error_threshold',
        default=5,
        help=('Number of reboots to allow before assuming '
              'a router needs manual intervention'),
    ),
    cfg.IntOpt(
        'num_worker_threads',
        default=4,
        help='the number of worker threads to run per process'),

]
CONF.register_opts(WORKER_OPTS)


def _normalize_uuid(value):
    return str(uuid.UUID(value.replace('-', '')))


class WorkerContext(object):
    """Holds resources owned by the worker and used by the Automaton.
    """

    def __init__(self):
        self.neutron = neutron.Neutron(cfg.CONF)
        self.nova_client = nova.Nova(cfg.CONF)


class Worker(object):
    """Manages state for the worker process.

    The Scheduler gets a callable as an argument, but we need to keep
    track of a bunch of the state machines, so the callable is a
    method of an instance of this class instead of a simple function.
    """
    def __init__(self, notifier):
        self._ignore_directory = cfg.CONF.ignored_router_directory
        self._queue_warning_threshold = cfg.CONF.queue_warning_threshold
        self._reboot_error_threshold = cfg.CONF.reboot_error_threshold
        self.work_queue = Queue.Queue()
        self.lock = threading.Lock()
        self._keep_going = True
        self.tenant_managers = {}
        # This process-global context should not be used in the
        # threads, since the clients are not thread-safe.
        self._context = WorkerContext()
        self.notifier = notifier
        # The notifier needs to be started here to ensure that it
        # happens inside the worker process and not the parent.
        self.notifier.start()

        # The DB is used for trakcing debug modes
        self.db_api = db_api.get_instance()

        # Thread locks for the routers so we only put one copy in the
        # work queue at a time
        self._router_locks = collections.defaultdict(threading.Lock)
        # Messages about what each thread is doing, keyed by thread id
        # and reported by the debug command.
        self._thread_status = {}
        # Start the threads last, so they can use the instance
        # variables created above.
        self.threads = [
            threading.Thread(
                name='t%02d' % i,
                target=self._thread_target,
            )
            for i in xrange(cfg.CONF.num_worker_threads)
        ]
        for t in self.threads:
            t.setDaemon(True)
            t.start()

    def _thread_target(self):
        """This method runs in each worker thread.
        """
        my_id = threading.current_thread().name
        LOG.debug('starting thread')
        # Use a separate context from the one we use when receiving
        # messages and talking to the tenant router manager because we
        # are in a different thread and the clients are not
        # thread-safe.
        context = WorkerContext()
        while self._keep_going:
            try:
                # Try to get a state machine from the work queue. If
                # there's nothing to do, we will block for a while.
                self._thread_status[my_id] = 'waiting for task'
                sm = self.work_queue.get(timeout=10)
            except Queue.Empty:
                continue
            if sm is None:
                LOG.info('received stop message')
                break

            # Make sure we didn't already have some updates under way
            # for a router we've been told to ignore for debug mode.
            should_ignore, reason = self.db_api.router_in_debug(sm.router_id)
            if should_ignore:
                LOG.debug('skipping update of router %s in debug mode ( '
                          'reason: ', sm.router_id, reason)
                continue
            # FIXME(dhellmann): Need to look at the router to see if
            # it belongs to a tenant which is in debug mode, but we
            # don't have that data in the sm, yet.
            LOG.debug('performing work on %s for tenant %s',
                      sm.router_id, sm.tenant_id)
            try:
                self._thread_status[my_id] = 'updating %s' % sm.router_id
                sm.update(context)
            except:
                LOG.exception('could not complete update for %s',
                              sm.router_id)
            finally:
                self._thread_status[my_id] = (
                    'finalizing task for %s' % sm.router_id
                )
                self.work_queue.task_done()
                with self.lock:
                    # Release the lock that prevents us from adding
                    # the state machine back into the queue. If we
                    # find more work, we will re-acquire it. If we do
                    # not find more work, we hold the primary work
                    # queue lock so the main thread cannot put the
                    # state machine back into the queue until we
                    # release that lock.
                    self._release_router_lock(sm)
                    # The state machine has indicated that it is done
                    # by returning. If there is more work for it to
                    # do, reschedule it by placing it at the end of
                    # the queue.
                    if sm.has_more_work():
                        LOG.debug('%s has more work, returning to work queue',
                                  sm.router_id)
                        self._add_router_to_work_queue(sm)
                    else:
                        LOG.debug('%s has no more work', sm.router_id)
        # Return the context object so tests can look at it
        self._thread_status[my_id] = 'exiting'
        return context

    def _shutdown(self):
        """Stop the worker.
        """
        self.report_status(show_config=False)
        # Tell the notifier to stop
        if self.notifier:
            self.notifier.stop()
        # Stop the worker threads
        self._keep_going = False
        # Drain the task queue by discarding it
        # FIXME(dhellmann): This could prevent us from deleting
        # routers that need to be deleted.
        self.work_queue = Queue.Queue()
        for t in self.threads:
            LOG.debug('sending stop message to %s', t.getName())
            self.work_queue.put((None, None))
        # Wait for our threads to finish
        for t in self.threads:
            LOG.debug('waiting for %s to finish', t.getName())
            t.join(timeout=5)
            LOG.debug('%s is %s', t.name,
                      'alive' if t.is_alive() else 'stopped')
        # Shutdown all of the tenant router managers. The lock is
        # probably not necessary, since this should be running in the
        # same thread where new messages are being received (and
        # therefore those messages aren't being processed).
        with self.lock:
            for trm in self.tenant_managers.values():
                LOG.debug('stopping tenant manager for %s', trm.tenant_id)
                trm.shutdown()

    def _get_trms(self, target):
        if target.lower() in commands.WILDCARDS:
            return list(self.tenant_managers.values())
        # Normalize the tenant id to a dash-separated UUID format.
        tenant_id = _normalize_uuid(target)
        if tenant_id not in self.tenant_managers:
            LOG.debug('creating tenant manager for %s', tenant_id)
            self.tenant_managers[tenant_id] = tenant.TenantRouterManager(
                tenant_id=tenant_id,
                notify_callback=self.notifier.publish,
                queue_warning_threshold=self._queue_warning_threshold,
                reboot_error_threshold=self._reboot_error_threshold,
            )
        return [self.tenant_managers[tenant_id]]

    def _should_process(self, message):
        """Determines whether a message should be processed or not."""
        global_debug, reason = self.db_api.global_debug()
        if global_debug:
            LOG.info('Skipping incoming event, cluster in global debug '
                     'mode. (reason: %s)' % reason)
            return False
        should_ignore, reason = self.db_api.tenant_in_debug(message.tenant_id)
        if should_ignore:
            LOG.info(
                'Ignoring message intended for tenant %s in debug mode '
                '(reason: %s): %s',
                message.tenant_id, reason, message,
            )
            return False
        return message

    def handle_message(self, target, message):
        """Callback to be used in main
        """
        LOG.debug('got: %s %r', target, message)
        if target is None:
            # We got the shutdown instruction from our parent process.
            self._shutdown()
            return
        if message.crud == event.COMMAND:
            self._dispatch_command(target, message)
        else:
            if not self._should_process(message):
                return
            # This is an update command for the router, so deliver it
            # to the state machine.
            with self.lock:
                self._deliver_message(target, message)

    _EVENT_COMMANDS = {
        commands.ROUTER_UPDATE: event.UPDATE,
        commands.ROUTER_REBUILD: event.REBUILD,
    }

    def _dispatch_command(self, target, message):
        instructions = message.body
        if instructions['command'] == commands.WORKERS_DEBUG:
            self.report_status()

        elif instructions['command'] == commands.ROUTER_DEBUG:
            router_id = instructions['router_id']
            reason = instructions.get('reason')
            if router_id in commands.WILDCARDS:
                LOG.warning(
                    'Ignoring instruction to debug all routers with %r',
                    router_id)
            else:
                LOG.info('Placing router %s in debug mode (reason: %s)',
                         router_id, reason)
                self.db_api.enable_router_debug(router_id, reason)

        elif instructions['command'] == commands.ROUTER_MANAGE:
            router_id = instructions['router_id']
            try:
                self.db_api.disable_router_debug(router_id)
                LOG.info('Resuming management of router %s', router_id)
            except KeyError:
                pass
            try:
                self._router_locks[router_id].release()
                LOG.info('Unlocked router %s', router_id)
            except KeyError:
                pass
            except threading.ThreadError:
                # Already unlocked, that's OK.
                pass

        elif instructions['command'] in self._EVENT_COMMANDS:
            new_msg = event.Event(
                tenant_id=message.tenant_id,
                router_id=message.router_id,
                crud=self._EVENT_COMMANDS[instructions['command']],
                body=instructions,
            )
            # Use handle_message() to ensure we acquire the lock
            LOG.info('sending %s instruction to %s',
                     instructions['command'], message.tenant_id)
            self.handle_message(new_msg.tenant_id, new_msg)
            LOG.info('forced %s for %s complete',
                     instructions['command'], message.tenant_id)

        elif instructions['command'] == commands.TENANT_DEBUG:
            tenant_id = instructions['tenant_id']
            reason = instructions.get('reason')
            if tenant_id in commands.WILDCARDS:
                LOG.warning(
                    'Ignoring instruction to debug all tenants with %r',
                    tenant_id)
            else:
                LOG.info('Placing tenant %s in debug mode (reason: %s)',
                         tenant_id, reason)
                self.db_api.enable_tenant_debug(tenant_id, reason)

        elif instructions['command'] == commands.TENANT_MANAGE:
            tenant_id = instructions['tenant_id']
            try:
                self.db_api.disable_tenant_debug(tenant_id)
                LOG.info('Resuming management of tenant %s', tenant_id)
            except KeyError:
                pass

        elif instructions['command'] == commands.GLOBAL_DEBUG:
            enable = instructions.get('enabled')
            reason = instructions.get('reason')
            if enable == 1:
                LOG.info('Enabling global debug mode (reason: %s)' % reason)
                self.db_api.enable_global_debug(reason)
            elif enable == 0:
                LOG.info('Disabling global debug mode')
                self.db_api.disable_global_debug()
            else:
                LOG.warn('Unrecognized global debug command: %s', instructions)
        elif instructions['command'] == commands.CONFIG_RELOAD:
            try:
                cfg.CONF()
            except Exception:
                LOG.exception('Could not reload configuration')
            else:
                cfg.CONF.log_opt_values(LOG, INFO)

        else:
            LOG.warn('unrecognized command: %s', instructions)

    def _deliver_message(self, target, message):
        LOG.debug('preparing to deliver %r to %r', message, target)
        trms = self._get_trms(target)
        for trm in trms:
            sms = trm.get_state_machines(message, self._context)
            for sm in sms:
                # NOTE(adam_g): We dont necessarily know the router_id
                # till the sm has been created. this check should move to
                # _should_process() once thats changed.
                should_ignore, reason = self.db_api.router_in_debug(
                    sm.router_id)
                if should_ignore:
                    LOG.info(
                        'Ignoring message intended for router %s in '
                        'debug mode (reason: %s): %s',
                        sm.router_id, reason, message,
                    )
                    continue
                # Add the message to the state machine's inbox. If
                # there is already a thread working on the router,
                # that thread will pick up the new work when it is
                # done with the current job. The work queue lock is
                # acquired before asking the state machine if it has
                # more work, so this block of code won't be executed
                # at the same time as the thread trying to decide if
                # the router is done.
                if sm.send_message(message):
                    self._add_router_to_work_queue(sm)

    def _add_router_to_work_queue(self, sm):
        """Queue up the state machine by router id.

        The work queue lock should be held before calling this method.
        """
        l = self._router_locks[sm.router_id]
        locked = l.acquire(False)
        if locked:
            self.work_queue.put(sm)
        else:
            LOG.debug('%s is already in the work queue', sm.router_id)

    def _release_router_lock(self, sm):
        self._router_locks[sm.router_id].release()

    def report_status(self, show_config=True):
        if show_config:
            cfg.CONF.log_opt_values(LOG, INFO)
        LOG.info(
            'Number of state machines in work queue: %d',
            self.work_queue.qsize()
        )
        LOG.info(
            'Number of tenant router managers managed: %d',
            len(self.tenant_managers)
        )
        for thread in self.threads:
            LOG.info(
                'Thread %s is %s. Last seen: %s',
                thread.name,
                'alive' if thread.isAlive() else 'DEAD',
                self._thread_status.get(thread.name, 'UNKNOWN'),
            )
        debug_tenants = self.db_api.tenants_in_debug()
        if debug_tenants:
            for t_uuid, reason in debug_tenants:
                LOG.info('Debugging tenant: %s (reason: %s)', t_uuid, reason)
        else:
            LOG.info('No tenants in debug mode')

        debug_routers = self.db_api.routers_in_debug()
        if self.db_api.routers_in_debug():
            for r_uuid, reason in debug_routers:
                LOG.info('Debugging router: %s (reason: %s)', r_uuid, reason)
        else:
            LOG.info('No routers in debug mode')
