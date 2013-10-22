"""Worker process parts.
"""

import logging
import Queue
import threading

from akanda.rug import tenant

LOG = logging.getLogger(__name__)


class Worker(object):
    """Manages state for the worker process.

    The Scheduler gets a callable as an argument, but we need to keep
    track of a bunch of the state machines, so the callable is a
    method of an instance of this class instead of a simple function.
    """

    def __init__(self, num_threads, notifier):
        self.work_queue = Queue.Queue()
        self.lock = threading.Lock()
        self._keep_going = True
        self.tenant_managers = {}
        self.being_updated = set()
        self.threads = [
            threading.Thread(
                name='worker-thread-%02d' % i,
                target=self._thread_target,
            )
            for i in xrange(num_threads)
        ]
        for t in self.threads:
            t.setDaemon(True)
            t.start()
        self.notifier = notifier
        # The notifier needs to be started here to ensure that it
        # happens inside the worker process and not the parent.
        self.notifier.start()

    def _thread_target(self):
        """This method runs in each worker thread.
        """
        LOG.debug('starting thread')
        while self._keep_going:
            try:
                # Try to get a state machine from the work queue. If
                # there's nothing to do, we will block for a while.
                sm = self.work_queue.get(timeout=10)
            except Queue.Empty:
                continue
            if not sm:
                break
            LOG.debug('updating %s with id %s', sm.router_id, sm)
            try:
                sm.update()
            except:
                LOG.exception('could not complete update for %s'
                              % sm.router_id)
            finally:
                self.work_queue.task_done()
                with self.lock:
                    # The state machine has indicated that it is done
                    # by returning. If there is more work for it to
                    # do, reschedule it by placing it at the end of
                    # the queue.
                    if sm.has_more_work():
                        self.work_queue.put(sm)
                    else:
                        self.being_updated.discard(sm.router_id)

    def _shutdown(self):
        """Stop the worker.
        """
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
            t.join(timeout=1)
        # Shutdown all of the tenant router managers. The lock is
        # probably not necessary, since this should be running in the
        # same thread where new messages are being received (and
        # therefore those messages aren't being processed).
        with self.lock:
            for trm in self.tenant_managers.values():
                LOG.debug('stopping tenant manager for %s', trm.tenant_id)
                trm.shutdown()

    def _get_trms(self, target):
        if target == '*':
            return list(self.tenant_managers.values())
        if target not in self.tenant_managers:
            LOG.debug('creating tenant manager for %s', target)
            self.tenant_managers[target] = tenant.TenantRouterManager(
                tenant_id=target,
                notify_callback=self.notifier.publish,
            )
        return [self.tenant_managers[target]]

    def handle_message(self, target, message):
        """Callback to be used in main
        """
        #LOG.debug('got: %s %r', target, message)
        if target is None:
            # We got the shutdown instruction from our parent process.
            self._shutdown()
            return
        if target == 'debug' and message.body['verbose'] == 1:
            self.report_status()
            return
        with self.lock:
            trms = self._get_trms(target)
            for trm in trms:
                sms = trm.get_state_machines(message)
                for sm in sms:
                    if sm.router_id not in self.being_updated:
                        # Queue up the state machine by router id.
                        # No work should be picked up, because we
                        # have the lock, so it doesn't matter that
                        # the queue is empty right now.
                        self.work_queue.put(sm)
                        self.being_updated.add(sm.router_id)
                    # Add the message to the state machine's inbox
                    sm.send_message(message)

    def report_status(self):
        LOG.debug(
            'Number of elements in the queue: %d',
            self.work_queue.qsize()
        )
        LOG.debug(
            'Number of tenant router managers managed: %d',
            len(self.tenant_managers)
        )
        for thread in self.threads:
            LOG.debug(
                'Thread %s is %s',
                thread.name, 'alive' if thread.isAlive() else 'DEAD')
