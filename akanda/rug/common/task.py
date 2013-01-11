import logging

import eventlet

LOG = logging.getLogger(__name__)


class Task(object):
    def __init__(self, method, data, max_attempts=3):
        self.method = method
        self.data = data
        self.current = 0
        self.max_attempts = max_attempts

    def __call__(self):
        self.current += 1
        self.method(self.data)

    def should_retry(self):
        return self.current < self.max_attempts

    def __repr__(self):
        msg = '<Task method: %s data: %s attempt: %d/%d >'

        return msg % (self.method.__name__,
                      self.data,
                      self.current,
                      self.max_attempts)


class TaskManager(object):
    def __init__(self, max_requeue_delay=10):
        self.task_queue = eventlet.queue.LightQueue()
        self.delay_queue = eventlet.queue.LightQueue()
        self.blocked = set()
        self.max_requeue_delay = max_requeue_delay

    def put(self, method, data, max_attempts=3):
        self.task_queue.put(Task(method, data, max_attempts))

    def start(self):
        eventlet.spawn(self._serialized_task_runner)
        eventlet.spawn(self._requeue_failed)

    def _serialized_task_runner(self):
        while True:
            LOG.info('Waiting on item')
            task = self.task_queue.get()
            try:
                task()
            except Exception, e:
                if isinstance(e, Warning):
                    LOG.warn('Task: %s' % task)
                else:
                    LOG.exception('Task failed: %s' % task)

                if task.should_retry():
                    self.delay_queue.put(task)
                else:
                    LOG.error('Task Error: %s' % task)

    def _requeue_failed(self):
        while True:
            eventlet.sleep(self.max_requeue_delay)
            LOG.info('requeueing delayed tasks')
            while True:
                try:
                    task = self.delay_queue.get_nowait()
                    self.task_queue.put(task)
                except eventlet.queue.Empty:
                    break
