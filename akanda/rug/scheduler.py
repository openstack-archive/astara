"""Scheduler to send messages for a given router to the correct worker.
"""

import logging
import multiprocessing
import signal
import uuid


LOG = logging.getLogger(__name__)


def _worker(inq, worker_factory):
    """Scheduler's worker process main function.
    """
    # Ignore SIGINT, since the parent will catch it and give us a
    # chance to exit cleanly.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    LOG.debug('starting worker process')
    worker = worker_factory()
    while True:
        data = inq.get()
        if data is None:
            target, message = None, None
        else:
            target, message = data
        try:
            worker.handle_message(target, message)
        except Exception:
            LOG.exception('Error processing data %s' % unicode(data))
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
        # If we get the wildcard target, send the message to all of
        # the workers.
        if target in ['*', 'debug']:
            return self.workers[:]
        idx = uuid.UUID(target).int % len(self.workers)
        return [self.workers[idx]]


class Scheduler(object):
    """Managers a worker pool and redistributes messages.
    """

    def __init__(self, num_workers, worker_factory):
        """
        :param num_workers: The number of worker processes to create.
        :type num_workers: int
        :param worker_func: Callable for the worker processes to use
                            when a notification is received.
        :type worker_factory: Callable to create Worker instances.
        """
        if num_workers < 1:
            raise ValueError('Need at least one worker process')
        self.num_workers = num_workers
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
                name='worker-%02d' % i,
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
            LOG.debug('waiting for %s', w['worker'].name)
            w['queue'].close()
            w['worker'].join()

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
