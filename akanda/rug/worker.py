"""Worker process parts.
"""

import logging

from akanda.rug import tenant

LOG = logging.getLogger(__name__)


class Worker(object):
    """Manages state for the worker process.

    The Scheduler gets a callable as an argument, but we need to keep
    track of a bunch of the state machines, so the callable is a
    method of an instance of this class instead of a simple function.
    """

    def __init__(self, num_threads):
        self.tenant_managers = {}

    def _shutdown(self):
        for trm in self.tenant_managers.values():
            trm.shutdown()

    def handle_message(self, target, message):
        """Callback to be used in main
        """
        #LOG.debug('got: %s %r', target, message)
        if target is None:
            # We got the shutdown instruction from our parent process.
            self._shutdown()
            return
        if target not in self.tenant_managers:
            LOG.debug('creating tenant manager for %s', target)
            self.tenant_managers[target] = tenant.TenantRouterManager(
                tenant_id=target,
            )
        trm = self.tenant_managers[target]
        trm.handle_message(message)
