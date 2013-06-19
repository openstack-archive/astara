import logging

import eventlet

from akanda.rug.common.exceptions import AbortTask


LOG = logging.getLogger(__name__)


class Task(object):
    def __init__(self, method, data, max_attempts=3, reason=None):
        self.method = method
        self.data = data
        self.current = 0
        self.max_attempts = max_attempts
        self.reason = reason

    def __call__(self):
        self.current += 1
        self.method(self.data)

    def should_retry(self):
        return self.current < self.max_attempts

    def __repr__(self):
        msg = '<Task method: %s reason: (%s) data: %s attempt: %d/%d >'

        return msg % (self.method.__name__,
                      self.reason,
                      self.data,
                      self.current,
                      self.max_attempts)


class TaskManager(object):
    def __init__(self, max_requeue_delay=10):
        self.task_queue = eventlet.queue.LightQueue()
        self.delay_queue = eventlet.queue.LightQueue()
        self.blocked = set()
        self.max_requeue_delay = max_requeue_delay

    def put(self, method, data, max_attempts=3, reason=None):
        self.task_queue.put(Task(method, data, max_attempts, reason))

    def start(self):
        eventlet.spawn(self._serialized_task_runner)
        eventlet.spawn(self._requeue_failed)

    def _serialized_task_runner(self):
        while True:
            LOG.info('Waiting on item')
            task = self.task_queue.get()
            try:
                LOG.debug('starting %s', task)
                task()
                LOG.debug('success for task %s', task)
            except AbortTask as e:
                LOG.warn('Task aborted: %s (%s)', e, task)
            except Exception as e:
                try:
                    if isinstance(e, Warning):
                        LOG.warn('Task: %s (%s)' % (e, task))
                    else:
                        LOG.exception('Task failed: %s (%s)' % (e, task))

                    if task.should_retry():
                        self.delay_queue.put(task)
                    else:
                        LOG.error('Task Error: %s (%s)' % (e, task))
                except Exception:
                    LOG.exception('Error processing exception in task')

    def _requeue_failed(self):
        while True:
            eventlet.sleep(self.max_requeue_delay)
            LOG.info('requeueing %d delayed tasks', self.delay_queue.qsize())
            while True:
                try:
                    task = self.delay_queue.get_nowait()
                    LOG.info('Requeueing Task: %s', task)
                    self.task_queue.put(task)
                except eventlet.queue.Empty:
                    break
