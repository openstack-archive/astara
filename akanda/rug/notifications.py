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


"""Listen for notifications.
"""

import Queue
import threading

from akanda.rug import commands
from akanda.rug import drivers
from akanda.rug import event
from akanda.rug.common import rpc
from akanda.rug.resource import Resource

from oslo_config import cfg
from oslo_context import context
from oslo_log import log as logging

from akanda.rug.common.i18n import _LE


cfg.CONF.register_group(cfg.OptGroup(name='rabbit',
                                     title='RabbitMQ options'))
RABBIT_OPTIONS = [
    cfg.IntOpt('max_retries', default=0,
               help='Maximum number of RabbitMQ connection retries. '
                    'Default is 0 (infinite retry count)'),
    cfg.IntOpt('interval_start', default=2,
               help='The starting interval time between connection '
                    'attempts.'),
    cfg.IntOpt('interval_step', default=2,
               help='The amount to increase the re-connection '
                    'interval by.'),
    cfg.IntOpt('interval_max', default=30,
               help='The maximum time interval to try between '
                    're-connection attempts.'),
]
cfg.CONF.register_opts(RABBIT_OPTIONS, group='rabbit')

NOTIFICATIONS_OPTS = [
    cfg.StrOpt('amqp-url',
               help='connection for AMQP server'),
    cfg.StrOpt('incoming-notifications-exchange',
               default='neutron',
               help='name of the exchange where we receive notifications'),
    cfg.StrOpt('outgoing-notifications-exchange',
               default='neutron',
               help='name of the exchange where we send notifications'),
    cfg.StrOpt('rpc-exchange',
               default='l3_agent_fanout',
               help='name of the exchange where we receive RPC calls'),
    cfg.StrOpt('neutron-control-exchange',
               default='neutron',
               help='The name of the exchange used by Neutron for RPCs')
]
cfg.CONF.register_opts(NOTIFICATIONS_OPTS)

LOG = logging.getLogger(__name__)


def _get_tenant_id_for_message(context, payload=None):
    """Find the tenant id in the incoming message."""

    # give priority to the tenant_id in the router dict if one
    # exists in the message
    if payload:
        for key in ('router', 'port', 'subnet'):
            if key in payload and payload[key].get('tenant_id'):
                val = payload[key]['tenant_id']
                return val

    for key in ['tenant_id', 'project_id']:
        if key in context:
            val = context[key]
            # Some notifications have None as the tenant id, but we
            # can't shard on None in the dispatcher, so treat those as
            # invalid.
            if val is not None:
                return val
    return None


_ROUTER_INTERFACE_NOTIFICATIONS = set([
    'router.interface.create',
    'router.interface.delete',
])

_ROUTER_INTERESTING_NOTIFICATIONS = set([
    'subnet.create.end',
    'subnet.change.end',
    'subnet.delete.end',
    'port.create.end',
    'port.change.end',
    'port.delete.end',
])


L3_AGENT_TOPIC = 'l3_agent'


class L3RPCEndpoint(object):
    """A RPC endpoint for servicing L3 Agent RPC requests"""
    def __init__(self, notification_queue):
        self.notification_queue = notification_queue

    def router_deleted(self, ctxt, router_id):
        tenant_id = _get_tenant_id_for_message(ctxt)

        resource = Resource('router', router_id, tenant_id)

        crud = event.DELETE
        e = event.Event(resource, crud, None)
        self.notification_queue.put((e.resource.tenant_id, e))


class NotificationsEndpoint(object):
    """A RPC endpoint for processing notification"""
    def __init__(self, notification_queue):
        self.notification_queue = notification_queue

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        tenant_id = _get_tenant_id_for_message(ctxt, payload)
        crud = event.UPDATE
        e = None
        events = []
        if event_type.startswith('akanda.rug.command'):
            LOG.debug('received a command: %r', payload)
            crud = event.COMMAND
            if payload.get('command') == commands.POLL:
                e = event.Event(
                    resource='*',
                    crud=event.POLL,
                    body={})
                self.notification_queue.put(('*', e))
                return
            else:
                # If the message does not specify a tenant, send it to everyone
                tenant_id = payload.get('tenant_id', '*')
                router_id = payload.get('router_id')
                resource = Resource(
                    driver='router', id=router_id, tenant_id=tenant_id)
                e = event.Event(resource, crud, payload)
        else:

            for driver in drivers.enabled_drivers():
                driver_event = driver.process_notification(
                    tenant_id, event_type, payload)
                if driver_event:
                    events.append(driver_event)

        if not events:
            LOG.debug('Could not construct any events from %s /w payload: %s',
                      event_type, payload)
            return

        LOG.debug('Generated %s events from %s /w payload: %s',
                  len(events), event_type, payload)

        for e in events:
            self.notification_queue.put((e.resource.tenant_id, e))


def listen(notification_queue):
    connection = rpc.Connection()
    # listen for neutron notifications
    connection.create_notification_listener(
        endpoints=[NotificationsEndpoint(notification_queue)],
        exchange=cfg.CONF.neutron_control_exchange,
    )
    connection.create_rpc_consumer(
        topic=L3_AGENT_TOPIC,
        endpoints=[L3RPCEndpoint(notification_queue)]
    )
    # NOTE(adam_g): We previously consumed dhcp_agent messages as well
    # as agent messgaes with hostname appended, do we need them still?
    connection.consume_in_threads()
    connection.close()


class Sender(object):
    "Send notification messages"

    def __init__(self, topic=None):
        self._notifier = None
        self.topic = topic

    def get_notifier(self):
        if not self._notifier:
            self._notifier = rpc.get_rpc_notifier(topic=self.topic)

    def send(self, event_type, message):
        self.get_notifier()
        ctxt = context.get_admin_context().to_dict()
        self._notifier.info(ctxt, event_type, message)


class Publisher(Sender):

    def __init__(self, topic=None):
        super(Publisher, self).__init__(topic)
        self._q = Queue.Queue()
        self._t = None

    def start(self):
        ready = threading.Event()
        self._t = threading.Thread(
            name='notification-publisher',
            target=self._send,
            args=(ready,),
        )
        self._t.setDaemon(True)
        self._t.start()
        # Block until the thread is ready for work, but use a timeout
        # in case of error in the thread.
        ready.wait(10)
        LOG.debug('started %s', self._t.getName())

    def stop(self):
        if self._t:
            LOG.debug('stopping %s', self._t.getName())
            self._q.put(None)
            self._t.join(timeout=1)
            self._t = None

    def publish(self, incoming):
        self._q.put(incoming)

    def _send(self, ready):
        """Deliver notification messages from the in-process queue
        to the appropriate topic via the AMQP service.
        """
        # setup notifier driver ahead a time
        self.get_notifier()
        # Tell the start() method that we have set up the AMQP
        # communication stuff and are ready to do some work.
        ready.set()
        while True:
            msg = self._q.get()
            if msg is None:
                break
            LOG.debug('sending notification %r', msg)
            try:
                self.send(event_type=msg['event_type'], message=msg['payload'])
            except Exception:
                LOG.exception(_LE('could not publish notification'))


class NoopPublisher(Publisher):
    """A Publisher that doesn't do anything.

    The code that publishes notifications is spread across several
    classes and cannot be easily disabled in configurations that do
    not require sending metrics to ceilometer.

    This class is used in place of the Publisher class to disable
    sending metrics without explicitly checking in various places
    across the code base.

    """

    def start(self):
        pass

    def stop(self):
        pass

    def publish(self, incoming):
        pass
