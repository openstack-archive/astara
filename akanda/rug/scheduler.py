"""Scheduler to send messages for a given router to the correct worker.
"""

import logging
import multiprocessing
import signal


LOG = logging.getLogger(__name__)


def _worker(inq, callback):
    """Scheduler's worker process main function.
    """
    # Ignore SIGINT, since the parent will catch it and give us a
    # chance to exit cleanly.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    LOG.debug('starting')
    while True:
        data = inq.get()
        try:
            callback(data)
        except Exception:
            LOG.exception('Error processing data %s' % data)
        if data is None:
            break
    LOG.debug('exiting')


class Scheduler(object):

    def __init__(self, num_workers, worker_func):
        """
        :param num_workers: The number of worker processes to create.
        :type num_workers: int
        :param worker_func: Callable for the worker processes to use
                            when a notification is received.
        :type worker_func: Callable taking one argument.
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
                    'callback': worker_func,
                },
                name='Worker %d' % i,
            )
            worker.start()
            self.workers.append({
                'queue': wq,
                'worker': worker,
            })

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

    def handle_message(self, message):
        """Call this method when a new notification message is delivered. The
        scheduler will distribute it to the appropriate worker.
        """
        # TODO(dhellmann): Need a real dispatching algorithm here.
        for w in self.workers:
            w['queue'].put(message)
