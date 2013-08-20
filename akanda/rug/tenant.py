"""Manage the routers for a given tenant.
"""

import logging

from akanda.rug.api import quantum
from akanda.rug import state
from akanda.rug.openstack.common import timeutils

from oslo.config import cfg

LOG = logging.getLogger(__name__)


class TenantRouterManager(object):
    """Keep track of the state machines for the routers for a given tenant.
    """

    def __init__(self, tenant_id, notifier):
        self.tenant_id = tenant_id
        self.notifier = notifier
        self.state_machines = {}
        self.quantum = quantum.Quantum(cfg.CONF)
        self._default_router_id = None

    def _delete_router(self, router_id):
        "Called when the Automaton decides the router can be deleted"
        if router_id in self.state_machines:
            LOG.debug('deleting state machine for %s', router_id)
            del self.state_machines[router_id]
        if self._default_router_id == router_id:
            self._default_router_id = None

    def shutdown(self):
        LOG.info('shutting down')
        for rid, sm in self.state_machines.items():
            try:
                sm.service_shutdown()
            except Exception:
                LOG.exception(
                    'Failed to shutdown state machine for %s' % rid
                )

    def _report_bandwidth(self, router_id, bandwidth):
        LOG.info('reporting bandwidth for %s', router_id)
        msg = {
            'tenant_id': self.tenant_id,
            'timestamp': timeutils.isotime(),
            'event_type': 'akanda.bandwidth.used',
            'payload': dict((b.pop('name'), b) for b in bandwidth),
            'router_id': router_id,
        }
        self.notifier.publish(msg)

    def get_state_machines(self, message):
        """Return the state machines and the queue for sending it messages for
        the router being addressed by the message.
        """
        router_id = message.router_id
        if not router_id:
            if self._default_router_id is None:
                LOG.debug('looking up router for tenant %s', message.tenant_id)
                router = self.quantum.get_router_for_tenant(message.tenant_id)
                self._default_router_id = router.id
            router_id = self._default_router_id

        elif router_id == '*':
            # All of our routers
            return list(self.state_machines.values())

        # An individual router by its id.
        if router_id not in self.state_machines:
            def deleter():
                self._delete_router(router_id)
            sm = state.Automaton(
                router_id=router_id,
                delete_callback=deleter,
                bandwidth_callback=self._report_bandwidth,
            )
            self.state_machines[router_id] = sm
        sm = self.state_machines[router_id]
        return [sm]
