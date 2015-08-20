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


"""Manage the resources for a given tenant.
"""

import collections
import threading

from oslo_log import log as logging

from akanda.rug.common.i18n import _LE
from akanda.rug import state
from akanda.rug import drivers
from akanda.rug.openstack.common import timeutils


LOG = logging.getLogger(__name__)


class InvalidIncomingMessage(Exception):
    pass


class ResourceContainer(object):

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

    def has_been_deleted(self, resource_id):
        with self.lock:
            return resource_id in self.deleted

    def __getitem__(self, item):
        with self.lock:
            return self.state_machines[item]

    def __setitem__(self, key, value):
        with self.lock:
            self.state_machines[key] = value

    def __contains__(self, item):
        with self.lock:
            return item in self.state_machines


class TenantResourceManager(object):
    """Keep track of the state machines for the logical resources for a given
    tenant.
    """

    def __init__(self, tenant_id, notify_callback,
                 queue_warning_threshold,
                 reboot_error_threshold):
        self.tenant_id = tenant_id
        self.notify = notify_callback
        self._queue_warning_threshold = queue_warning_threshold
        self._reboot_error_threshold = reboot_error_threshold
        self.state_machines = ResourceContainer()
        self._default_resource_id = None

    def _delete_resource(self, resource_id):
        "Called when the Automaton decides the resource can be deleted"
        if resource_id in self.state_machines:
            LOG.debug('deleting state machine for %s', resource_id)
            del self.state_machines[resource_id]
        if self._default_resource_id == resource_id:
            self._default_resource_id = None

    def shutdown(self):
        LOG.info('shutting down')
        for resource_id, sm in self.state_machines.items():
            try:
                sm.service_shutdown()
            except Exception:
                LOG.exception(_LE(
                    'Failed to shutdown state machine for %s'), resource_id
                )

    def _report_bandwidth(self, resource_id, bandwidth):
        LOG.debug('reporting bandwidth for %s', resource_id)
        msg = {
            'tenant_id': self.tenant_id,
            'timestamp': timeutils.isotime(),
            'event_type': 'akanda.bandwidth.used',
            'payload': dict((b.pop('name'), b) for b in bandwidth),
            'uuid': resource_id,
        }
        self.notify(msg)

    def get_state_machines(self, message, worker_context):
        """Return the state machines and the queue for sending it messages for
        the logical resource being addressed by the message.
        """
        if (not message.resource or
           (message.resource and not message.resource.id)):
                LOG.error(_LE(
                    'Cannot get state machine for message with '
                    'no message.resource'))
                raise InvalidIncomingMessage()

        state_machines = []

        # Send to all of our resources.
        if message.resource.id == '*':
            LOG.debug('routing to all state machines')
            state_machines = self.state_machines.values()

        # Ignore messages to deleted resources.
        elif self.state_machines.has_been_deleted(message.resource.id):
            LOG.debug('dropping message for deleted resource')
            return []

        # Send to resources that have an ERROR status
        elif message.resource == 'error':
            state_machines = [
                sm for sm in self.state_machines.values()
                if sm.has_error()
            ]
            LOG.debug('routing to %d errored state machines',
                      len(state_machines))

        # Create a new state machine for this router.
        elif message.resource.id not in self.state_machines:
            LOG.debug('creating state machine for %s', message.resource.id)

            # load the driver
            if not message.resource.driver:
                LOG.error(_LE('cannot create state machine without specifying'
                              'a driver.'))
                return []

            # load the driver
            driver_obj = \
                drivers.get(message.resource.driver)(worker_context,
                                                     message.resource.id)

            if not driver_obj:
                # this means the driver didn't load for some reason..
                # this might not be needed at all.
                LOG.debug('for some reason loading the driver failed')
                return []

            def deleter():
                self._delete_resource(message.resource.id)

            new_state_machine = state.Automaton(
                driver=driver_obj,
                resource_id=message.resource.id,
                tenant_id=self.tenant_id,
                delete_callback=deleter,
                bandwidth_callback=self._report_bandwidth,
                worker_context=worker_context,
                queue_warning_threshold=self._queue_warning_threshold,
                reboot_error_threshold=self._reboot_error_threshold,
            )
            self.state_machines[message.resource.id] = new_state_machine
            state_machines = [new_state_machine]

        # Send directly to an existing router.
        elif message.resource.id:
            state_machines = [self.state_machines[message.resource.id]]

        # Filter out any deleted state machines.
        return [
            machine
            for machine in state_machines
            if (not machine.deleted and
                not self.state_machines.has_been_deleted(machine.resource_id))
        ]
