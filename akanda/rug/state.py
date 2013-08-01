"""State machine for managing a router.
"""

import logging


class Automaton(object):

    def __init__(self, router_id, delete_callback):
        """
        :param router_id: UUID of the router being managed
        :type router_id: str
        :param delete_callback: Invoked when the Automaton decides
                                the router should be deleted.
        :type delete_callback: callable
        """
        self.router_id = router_id
        self.delete_callback = delete_callback
        self.log = logging.getLogger(__name__ + '.' + router_id)

    def service_shutdown(self):
        "Called when the parent process is being stopped"

    def update(self, message):
        "Called when the router config should be changed"
        self.log.debug('update: %r', message)
        # TODO: Manage the router!
