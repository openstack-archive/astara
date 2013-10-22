"""Manage the routers for a given tenant.
"""

import collections
import logging
import threading

from akanda.rug.api import quantum
from akanda.rug import state
from akanda.rug.openstack.common import timeutils

from oslo.config import cfg

LOG = logging.getLogger(__name__)


class RouterContainer(object):

    def __init__(self):
        self.state_machines = {}
        self.deleted = collections.deque(maxlen=50)
        self.lock = threading.Lock()

    def __delitem__(self, item):
        with self.lock:
            del self.state_machines[item]
            self.deleted.append(item)

    def items(self):
        with self.lock:
            return list(self.state_machines.items())

    def values(self):
        with self.lock:
            return list(self.state_machines.values())

    def has_been_deleted(self, router_id):
        with self.lock:
            return router_id in self.deleted

    def __getitem__(self, item):
        with self.lock:
            return self.state_machines[item]

    def __setitem__(self, key, value):
        with self.lock:
            self.state_machines[key] = value

    def __contains__(self, item):
        with self.lock:
            return item in self.state_machines


class TenantRouterManager(object):
    """Keep track of the state machines for the routers for a given tenant.
    """

    def __init__(self, tenant_id, notify_callback):
        self.tenant_id = tenant_id
        self.notify = notify_callback
        self.state_machines = RouterContainer()
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
        self.notify(msg)

    def get_state_machines(self, message):
        """Return the state machines and the queue for sending it messages for
        the router being addressed by the message.
        """
        router_id = message.router_id
        if not router_id:
            if self._default_router_id is None:
                LOG.debug('looking up router for tenant %s', message.tenant_id)
                #TODO(mark): handle muliple router lookup
                router = self.quantum.get_router_for_tenant(message.tenant_id)
                if not router:
                    LOG.debug(
                        'router not found for tenant %s',
                        message.tenant_id
                    )
                    return []
                self._default_router_id = router.id
            router_id = self._default_router_id

        elif router_id == '*':
            # All of our routers
            return list(self.state_machines.values())

        # Ignore messages to deleted routers.
        if self.state_machines.has_been_deleted(router_id):
            return []

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
