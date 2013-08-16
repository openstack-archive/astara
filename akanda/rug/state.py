"""State machine for managing a router.
"""

import logging


class Automaton(object):

    def __init__(self, router_id, delete_callback, queue):
        """
        :param router_id: UUID of the router being managed
        :type router_id: str
        :param delete_callback: Invoked when the Automaton decides
                                the router should be deleted.
        :type delete_callback: callable
        :param queue: Input queue for messages
        :type queue: Queue.Queue
        """
        self.router_id = router_id
        self.delete_callback = delete_callback
        self.queue = queue
        self.log = logging.getLogger(__name__ + '.' + router_id)

    def service_shutdown(self):
        "Called when the parent process is being stopped"

    def update(self):
        "Called when the router config should be changed"
        while not self.queue.empty():
            message = self.queue.get()
            self.log.debug('update: %r', message)
            # TODO: Manage the router!

    def send_message(self, message):
        self.queue.put(message)

    def has_more_work(self):
        return not self.queue.empty()
