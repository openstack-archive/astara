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

from akanda.rug.common import log_shim as logging
import Queue
import urlparse
import threading
import uuid
import time
import socket

import kombu
import kombu.connection
import kombu.entity
import kombu.messaging

from akanda.rug import commands
from akanda.rug import event
from akanda.rug.common import rpc

from oslo.config import cfg
from oslo_context import context


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


_INTERFACE_NOTIFICATIONS = set([
    'router.interface.create',
    'router.interface.delete',
])

_INTERESTING_NOTIFICATIONS = set([
    'subnet.create.end',
    'subnet.change.end',
    'subnet.delete.end',
    'port.create.end',
    'port.change.end',
    'port.delete.end',
])


L3_AGENT_TOPIC = 'l3_agent'


def _handle_connection_error(exception, interval):
    """ Log connection retry attempts."""
    LOG.warn("Error establishing connection: %s", exception)
    LOG.warn("Retrying in %d seconds", interval)


def _kombu_configuration(conf):
    """Return a dict of kombu connection parameters from oslo.config."""
    cfg_keys = ('max_retries',
                'interval_start',
                'interval_step',
                'interval_max')
    return {k: getattr(conf.CONF.rabbit, k) for k in cfg_keys}


class L3RPCEndpoint(object):
    """A RPC endpoint for servicing L3 Agent RPC requests"""
    def __init__(self, notification_queue):
        self.notification_queue = notification_queue

    def router_deleted(self, ctxt, router_id):
        tenant_id = _get_tenant_id_for_message(ctxt)
        crud = event.DELETE
        e = event.Event(tenant_id, router_id, crud, None)
        self.notification_queue.put((e.tenant_id, e))


class NotificationsEndpoint(object):
    """A RPC endpoint for processing notification"""
    def __init__(self, notification_queue):
        self.notification_queue = notification_queue

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        # Router id is not always present, but look for it as though
        # it is to avoid duplicating this line a few times.
        router_id = payload.get('router', {}).get('id')
        tenant_id = _get_tenant_id_for_message(ctxt, payload)
        crud = event.UPDATE
        if event_type.startswith('routerstatus.update'):
            # We generate these events ourself, so ignore them.
            return None
        if event_type == 'router.create.end':
            crud = event.CREATE
        elif event_type == 'router.delete.end':
            crud = event.DELETE
            router_id = payload.get('router_id')
        elif event_type in _INTERFACE_NOTIFICATIONS:
            crud = event.UPDATE
            router_id = payload.get('router.interface', {}).get('id')
        elif event_type in _INTERESTING_NOTIFICATIONS:
            crud = event.UPDATE
        elif event_type.endswith('.end'):
            crud = event.UPDATE
        elif event_type.startswith('akanda.rug.command'):
            LOG.debug('received a command: %r', message.get('payload'))
            # If the message does not specify a tenant, send it to everyone
            tenant_id = payload.get('tenant_id', '*')
            router_id = payload.get('router_id')
            crud = event.COMMAND
            if payload.get('command') == commands.POLL:
                return event.Event(
                    tenant_id='*',
                    router_id='*',
                    crud=event.POLL,
                    body={},
                )
        else:
            return

        e = event.Event(tenant_id, router_id, crud, payload)
        self.notification_queue.put((e.tenant_id, e))


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
    while True:
        pass


class Sender(object):
    "Send notification messages"

    def __init__(self, amqp_url, exchange_name, topic):
        self.amqp_url = amqp_url
        self.exchange_name = exchange_name
        self.topic = topic

    def __enter__(self):
        LOG.debug('setting up notification sender for %s to %s',
                  self.topic, self.amqp_url)

        # Pre-pack the context in the format used by
        # openstack.common.rpc.amqp.pack_context(). Since we always
        # use the same context, there is no reason to repack it every
        # time we get a new message.
        self._context = context.get_admin_context()
        self._packed_context = dict(
            ('_context_%s' % key, value)
            for (key, value) in self._context.to_dict().iteritems()
        )

        # We expect to be created in one process and then used in
        # another, so we delay creating any actual AMQP connections or
        # other resources until we're going to use them.
        conn_info = urlparse.urlparse(self.amqp_url)
        self._connection = kombu.connection.BrokerConnection(
            hostname=conn_info.hostname,
            userid=conn_info.username,
            password=conn_info.password,
            virtual_host=conn_info.path,
            port=conn_info.port,
        )
        self._connection.connect()
        self._channel = self._connection.channel()

        # Use the same exchange where we're receiving notifications
        self._notifications_exchange = kombu.entity.Exchange(
            name=self.exchange_name,
            type='topic',
            durable=False,
            auto_delete=False,
            internal=False,
            channel=self._channel,
        )

        self._producer = kombu.Producer(
            channel=self._channel,
            exchange=self._notifications_exchange,
            routing_key=self.topic,
        )
        return self

    def __exit__(self, *args):
        self._connection.release()

    def send(self, incoming):
        msg = {}
        msg.update(incoming)
        # Do the work of openstack.common.rpc.amqp._add_unique_id()
        msg['_unique_id'] = uuid.uuid4().hex
        # Add our context, in the way of
        # openstack.common.rpc.amqp.pack_context()
        msg.update(self._packed_context)
        self._producer.publish(msg)


class Publisher(object):

    def __init__(self, amqp_url, exchange_name, topic):
        self.amqp_url = amqp_url
        self.exchange_name = exchange_name
        self.topic = topic
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
        with Sender(self.amqp_url, self.exchange_name, self.topic) as sender:
            # Tell the start() method that we have set up the AMQP
            # communication stuff and are ready to do some work.
            ready.set()

            while True:
                msg = self._q.get()
                if msg is None:
                    break
                LOG.debug('sending notification %r', msg)
                try:
                    sender.send(msg)
                except Exception:
                    LOG.exception('could not publish notification')


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
