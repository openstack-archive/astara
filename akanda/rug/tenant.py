# Copyright 2014 DreamHost, LLC
#
# Author: DreamHost, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


"""Manage the routers for a given tenant.
"""

import collections
import threading

from oslo_log import log as logging

from akanda.rug.common.i18n import _LE
from akanda.rug import state
from akanda.rug.openstack.common import timeutils


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

    def __init__(self, tenant_id, notify_callback,
                 queue_warning_threshold,
                 reboot_error_threshold):
        self.tenant_id = tenant_id
        self.notify = notify_callback
        self._queue_warning_threshold = queue_warning_threshold
        self._reboot_error_threshold = reboot_error_threshold
        self.state_machines = RouterContainer()
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
                LOG.exception(_LE(
                    'Failed to shutdown state machine for %s'), rid
                )

    def _report_bandwidth(self, router_id, bandwidth):
        LOG.debug('reporting bandwidth for %s', router_id)
        msg = {
            'tenant_id': self.tenant_id,
            'timestamp': timeutils.isotime(),
            'event_type': 'akanda.bandwidth.used',
            'payload': dict((b.pop('name'), b) for b in bandwidth),
            'router_id': router_id,
        }
        self.notify(msg)

    def get_state_machines(self, message, worker_context):
        """Return the state machines and the queue for sending it messages for
        the router being addressed by the message.
        """
        router_id = message.router_id
        if not router_id:
            LOG.debug('looking for router for %s', message.tenant_id)
            if self._default_router_id is None:
                # TODO(mark): handle muliple router lookup
                router = worker_context.neutron.get_router_for_tenant(
                    message.tenant_id,
                )
                if not router:
                    LOG.debug(
                        'router not found for tenant %s',
                        message.tenant_id
                    )
                    return []
                self._default_router_id = router.id
            router_id = self._default_router_id
            LOG.debug('using router id %s', router_id)

        # Ignore messages to deleted routers.
        if self.state_machines.has_been_deleted(router_id):
            LOG.debug('dropping message for deleted router')
            return []

        state_machines = []

        # Send to all of our routers.
        if router_id == '*':
            LOG.debug('routing to all state machines')
            state_machines = self.state_machines.values()

        # Send to routers that have an ERROR status
        elif router_id == 'error':
            state_machines = [
                sm for sm in self.state_machines.values()
                if sm.has_error()
            ]
            LOG.debug('routing to %d errored state machines',
                      len(state_machines))

        # Create a new state machine for this router.
        elif router_id not in self.state_machines:
            LOG.debug('creating state machine for %s', router_id)

            def deleter():
                self._delete_router(router_id)

            sm = state.Automaton(
                router_id=router_id,
                tenant_id=self.tenant_id,
                delete_callback=deleter,
                bandwidth_callback=self._report_bandwidth,
                worker_context=worker_context,
                queue_warning_threshold=self._queue_warning_threshold,
                reboot_error_threshold=self._reboot_error_threshold,
            )
            self.state_machines[router_id] = sm
            state_machines = [sm]

        # Send directly to an existing router.
        elif router_id:
            sm = self.state_machines[router_id]
            state_machines = [sm]

        # Filter out any deleted state machines.
        return [
            machine
            for machine in state_machines
            if (not machine.deleted and
                not self.state_machines.has_been_deleted(machine.router_id))
        ]
