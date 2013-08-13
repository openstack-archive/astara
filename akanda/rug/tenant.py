"""Manage the routers for a given tenant.
"""

import logging

from akanda.rug import state

LOG = logging.getLogger(__name__)


class TenantRouterManager(object):
    """Keep track of the state machines for the routers for a given tenant.
    """

    def __init__(self, tenant_id):
        self.state_machines = {}

    def _delete_router(self, router_id):
        "Called when the Automaton decides the router can be deleted"
        if router_id in self.state_machines:
            LOG.debug('deleting state machine for %s', router_id)
            del self.state_machines[router_id]

    def shutdown(self):
        LOG.info('shutting down')
        for rid, sm in self.state_machines.items():
            try:
                sm.service_shutdown()
            except Exception:
                LOG.exception(
                    'Failed to shutdown state machine for %s' % rid
                )

    def handle_message(self, message):
        router_id = message.router_id
        if router_id is None:
            LOG.debug('do not know how to handle %r', message)
        else:
            if router_id not in self.state_machines:
                self.state_machines[router_id] = state.Automaton(
                    router_id=router_id,
                    delete_callback=self._delete_router,
                )
            sm = self.state_machines[router_id]
            sm.update(message)

