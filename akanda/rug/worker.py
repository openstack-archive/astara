"""Worker process parts.
"""

import logging

from akanda.rug import state

LOG = logging.getLogger(__name__)


class Worker(object):
    """Manages state for the worker process.

    The Scheduler gets a callable as an argument, but we need to keep
    track of a bunch of the state machines, so the callable is a
    method of an instance of this class instead of a simple function.
    """

    def __init__(self):
        self.state_machines = {}

    def _delete_router(self, router_id):
        "Called when the Automaton decides the router can be deleted"
        if router_id in self.state_machines:
            LOG.debug('deleting state machine for %s', router_id)
            del self.state_machines[router_id]

    def _shutdown(self):
        LOG.info('shutting down')
        for rid, sm in self.state_machines.items():
            try:
                sm.service_shutdown()
            except Exception:
                LOG.exception(
                    'Failed to shutdown state machine for %s' % rid
                )

    def handle_message(self, target, message):
        """Callback to be used in main
        """
        #LOG.debug('got: %s %r', target, message)
        if target is None:
            # We got the shutdown instruction from our parent process.
            self._shutdown()
            return
        # FIXME(dhellmann): The "target" value is now the tenant id,
        # not the router id. We need to convert to the router id.
        if target not in self.state_machines:
            LOG.debug('creating state machine for %s', target)
            self.state_machines[target] = state.Automaton(
                router_id=target,
                delete_callback=self._delete_router,
            )
        sm = self.state_machines.get(target)
        sm.update(message)
