"""Manage the routers for a given tenant.
"""

import logging
import Queue

from akanda.rug import state

LOG = logging.getLogger(__name__)


class TenantRouterManager(object):
    """Keep track of the state machines for the routers for a given tenant.
    """

    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
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

    def get_state_machine(self, message):
        """Return the state machine and the queue for sending it messages for
        the router being addressed by the message.
        """
        router_id = message.router_id
        if not router_id:
            # FIXME(dhellmann): Need to look up the "default" router
            # for a tenant here.
            raise RuntimeError('do not know how to handle %r', message)
        if router_id not in self.state_machines:
            def deleter():
                self._delete_router(router_id)
            q = Queue.Queue()
            sm = state.Automaton(
                router_id=router_id,
                delete_callback=deleter,
                queue=q,
            )
            self.state_machines[router_id] = {
                'sm': sm,
                'inq': q,
            }
        sm = self.state_machines[router_id]
        return sm['sm'], sm['inq']
