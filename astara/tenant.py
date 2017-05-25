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

import datetime

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from astara import state
from astara import drivers
from astara.common import container


LOG = logging.getLogger(__name__)

tenant_opts = [
    cfg.BoolOpt('enable_byonf', default=False,
                help='Whether to enable bring-your-own-network-function '
                     'support via operator supplied drivers and images.'),
]
cfg.CONF.register_opts(tenant_opts)


class InvalidIncomingMessage(Exception):
    pass


class StateMachineContainer(container.ResourceContainer):
    def unmanage(self, resource_id):
        """Used to delete a state machine from local management

        Removes the local state machine from orchestrator management during
        cluster events.  This is different than deleting the resource in that
        it does not tag the resource as also deleted from Neutron, which would
        prevent us from recreating its state machine if the resource later ends
        up back under this orchestrators control.

        :param resource_id: The resource id to unmanage
        """
        try:
            with self.lock:
                sm = self.resources.pop(resource_id)
                sm.drop_queue()
                LOG.debug('unmanaged tenant state machine for resource %s',
                          resource_id)
        except KeyError:
            pass


class TenantResourceManager(object):
    """Keep track of the state machines for the logical resources for a given
    tenant.
    """

    def __init__(self, tenant_id, delete_callback, notify_callback,
                 queue_warning_threshold,
                 reboot_error_threshold):
        self.tenant_id = tenant_id
        self.delete = delete_callback
        self.notify = notify_callback
        self._queue_warning_threshold = queue_warning_threshold
        self._reboot_error_threshold = reboot_error_threshold
        self.state_machines = StateMachineContainer()
        self._default_resource_id = None

    def _delete_resource(self, resource):
        "Called when the Automaton decides the resource can be deleted"
        if resource.id in self.state_machines:
            LOG.debug('deleting state machine for %s', resource.id)
            del self.state_machines[resource.id]
        if self._default_resource_id == resource.id:
            self._default_resource_id = None
        self.delete(resource)

    def unmanage_resource(self, resource_id):
        self.state_machines.unmanage(resource_id)

    def shutdown(self):
        LOG.info('shutting down')
        for resource_id, sm in self.state_machines.items():
            try:
                sm.service_shutdown()
            except Exception:
                LOG.exception(
                    'Failed to shutdown state machine for %s', resource_id
                )

    def _report_bandwidth(self, resource_id, bandwidth):
        LOG.debug('reporting bandwidth for %s', resource_id)
        msg = {
            'tenant_id': self.tenant_id,
            'timestamp': datetime.datetime.isoformat(timeutils.utcnow()),
            'event_type': 'astara.bandwidth.used',
            'payload': dict((b.pop('name'), b) for b in bandwidth),
            'uuid': resource_id,
        }
        self.notify(msg)

    def get_all_state_machines(self):
        return self.state_machines.values()

    def get_state_machines(self, message, worker_context):
        """Return the state machines and the queue for sending it messages for
        the logical resource being addressed by the message.
        """
        if (not message.resource or
           (message.resource and not message.resource.id)):
                LOG.error(
                    'Cannot get state machine for message with '
                    'no message.resource')
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
        elif message.resource.id == 'error':
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
                LOG.error('cannot create state machine without specifying'
                          'a driver.')
                return []

            resource_obj = self._load_resource_from_message(
                worker_context, message)

            if not resource_obj:
                # this means the driver didn't load for some reason..
                # this might not be needed at all.
                LOG.debug('for some reason loading the driver failed')
                return []

            def deleter():
                self._delete_resource(message.resource)

            new_state_machine = state.Automaton(
                resource=resource_obj,
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
                not self.state_machines.has_been_deleted(machine.resource.id))
        ]

    def get_state_machine_by_resource_id(self, resource_id):
        try:
            return self.state_machines[resource_id]
        except KeyError:
            return None

    def _load_resource_from_message(self, worker_context, message):
        if cfg.CONF.enable_byonf:
            byonf_res = worker_context.neutron.tenant_has_byo_for_function(
                tenant_id=self.tenant_id.replace('-', ''),
                function_type=message.resource.driver)

            if byonf_res:
                try:
                    return drivers.load_from_byonf(
                        worker_context,
                        byonf_res,
                        message.resource.id)
                except drivers.InvalidDriverException:
                    LOG.exception(
                        'Could not load BYONF driver, falling back to '
                        'configured image')
                    pass

        return drivers.get(message.resource.driver)(
            worker_context, message.resource.id)
