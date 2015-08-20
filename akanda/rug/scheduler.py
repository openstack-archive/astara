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


"""Scheduler to send messages for a given router to the correct worker.
"""

import multiprocessing
import uuid

from oslo_config import cfg
from oslo_log import log as logging

from akanda.rug import commands
from akanda.rug.common.i18n import _, _LE, _LI, _LW
from akanda.rug import daemon


LOG = logging.getLogger(__name__)
CONF = cfg.CONF
SCHEDULER_OPTS = [
    cfg.IntOpt('num_worker_processes',
               default=16,
               help='the number of worker processes to run'),
]
CONF.register_opts(SCHEDULER_OPTS)


def _worker(inq, worker_factory):
    """Scheduler's worker process main function.
    """
    daemon.ignore_signals()
    LOG.debug('starting worker process')
    worker = worker_factory()
    while True:
        try:
            data = inq.get()
        except IOError:
            # NOTE(dhellmann): Likely caused by a signal arriving
            # during processing, especially SIGCHLD.
            data = None
        if data is None:
            target, message = None, None
        else:
            target, message = data
        try:
            worker.handle_message(target, message)
        except Exception:
            LOG.exception(_LE('Error processing data %s'), unicode(data))
        if data is None:
            break
    LOG.debug('exiting')


class Dispatcher(object):
    """Choose one of the workers to receive a message.

    The current implementation uses the least significant bits of the
    UUID as an integer to shard across the worker pool.
    """

    def __init__(self, workers):
        self.workers = workers

    def pick_workers(self, target):
        """Returns the workers that match the target.
        """
        target = target.strip() if target else None
        # If we get any wildcard target, send the message to all of
        # the workers.
        if target in commands.WILDCARDS:
            return self.workers[:]
        try:
            idx = uuid.UUID(target).int % len(self.workers)
        except (TypeError, ValueError) as e:
            LOG.warning(_LW(
                'Could not determine UUID from %r: %s, ignoring message'),
                target, e,
            )
            return []
        else:
            LOG.debug('target %s maps to worker %s', target, idx)
        return [self.workers[idx]]


class Scheduler(object):
    """Manages a worker pool and redistributes messages.
    """

    def __init__(self, worker_factory):
        """
        :param num_workers: The number of worker processes to create.
        :type num_workers: int
        :param worker_func: Callable for the worker processes to use
                            when a notification is received.
        :type worker_factory: Callable to create Worker instances.
        """
        self.num_workers = cfg.CONF.num_worker_processes
        if self.num_workers < 1:
            raise ValueError(_('Need at least one worker process'))
        self.workers = []
        # Create several worker processes, each with its own queue for
        # sending it instructions based on the notifications we get
        # when someone calls our handle_message() method.
        for i in range(self.num_workers):
            wq = multiprocessing.JoinableQueue()
            worker = multiprocessing.Process(
                target=_worker,
                kwargs={
                    'inq': wq,
                    'worker_factory': worker_factory,
                },
                name='p%02d' % i,
            )
            worker.start()
            self.workers.append({
                'queue': wq,
                'worker': worker,
            })
        self.dispatcher = Dispatcher(self.workers)

    def stop(self):
        """Shutdown all workers cleanly.
        """
        LOG.info('shutting down scheduler')
        # Send a poison pill to all of the workers
        for w in self.workers:
            LOG.debug('sending stop message to %s', w['worker'].name)
            w['queue'].put(None)
        # Wait for the workers to finish and be ready to exit.
        for w in self.workers:
            LOG.debug('waiting for queue for %s', w['worker'].name)
            w['queue'].close()
            LOG.debug('waiting for worker %s', w['worker'].name)
            w['worker'].join()
        LOG.info(_LI('scheduler shutdown'))

    def handle_message(self, target, message):
        """Call this method when a new notification message is delivered. The
        scheduler will distribute it to the appropriate worker.

        :param target: UUID of the resource that needs to get the message.
        :type target: uuid
        :param message: Dictionary full of data to send to the target.
        :type message: dict
        """
        for w in self.dispatcher.pick_workers(target):
            w['queue'].put((target, message))
