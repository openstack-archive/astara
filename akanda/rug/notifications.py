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

import logging
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

from akanda.rug.openstack.common.rpc import common as rpc_common

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


def _get_tenant_id_for_message(message):
    """Find the tenant id in the incoming message."""

    # give priority to the tenant_id in the router dict if one
    # exists in the message
    payload = message.get('payload', {})

    for key in ('router', 'port', 'subnet'):
        if key in payload and payload[key].get('tenant_id'):
            val = payload[key]['tenant_id']
            # LOG.debug('using tenant id from payload["%s"]["tenant_id"] = %s',
            #           key, val)
            return val

    for key in ['_context_tenant_id', '_context_project_id']:
        if key in message:
            val = message[key]
            # Some notifications have None as the tenant id, but we
            # can't shard on None in the dispatcher, so treat those as
            # invalid.
            if val is not None:
                # LOG.debug('using tenant id from message["%s"] = %s',
                #           key, val)
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


def _make_event_from_message(message):
    """Turn a raw message from the wire into an event.Event object
    """
    if 'oslo.message' in message:
        # Unpack the RPC call body and discard the envelope
        message = rpc_common.deserialize_msg(message)
    tenant_id = _get_tenant_id_for_message(message)
    crud = event.UPDATE
    router_id = None
    if message.get('method') == 'router_deleted':
        crud = event.DELETE
        router_id = message.get('args', {}).get('router_id')
    else:
        event_type = message.get('event_type', '')
        # Router id is not always present, but look for it as though
        # it is to avoid duplicating this line a few times.
        router_id = message.get('payload', {}).get('router', {}).get('id')
        if event_type.startswith('routerstatus.update'):
            # We generate these events ourself, so ignore them.
            return None
        if event_type == 'router.create.end':
            crud = event.CREATE
        elif event_type == 'router.delete.end':
            crud = event.DELETE
            router_id = message.get('payload', {}).get('router_id')
        elif event_type in _INTERFACE_NOTIFICATIONS:
            crud = event.UPDATE
            router_id = message.get(
                'payload', {}
            ).get('router.interface', {}).get('id')
        elif event_type in _INTERESTING_NOTIFICATIONS:
            crud = event.UPDATE
        elif event_type.endswith('.end'):
            crud = event.UPDATE
        elif event_type.startswith('akanda.rug.command'):
            LOG.debug('received a command: %r', message.get('payload'))
            # If the message does not specify a tenant, send it to everyone
            pl = message.get('payload', {})
            tenant_id = pl.get('tenant_id', '*')
            router_id = pl.get('router_id')
            crud = event.COMMAND
            if pl.get('command') == commands.POLL:
                return event.Event(
                    tenant_id='*',
                    router_id='*',
                    crud=event.POLL,
                    body={},
                )
        else:
            # LOG.debug('ignoring message %r', message)
            return None

    return event.Event(tenant_id, router_id, crud, message)


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


def listen(host_id, amqp_url,
           notifications_exchange_name, rpc_exchange_name,
           notification_queue):
    """Listen for messages from AMQP and deliver them to the
    in-process queue provided.
    """
    LOG.debug('%s starting to listen on %s', host_id, amqp_url)

    conn_info = urlparse.urlparse(amqp_url)
    connection = kombu.connection.BrokerConnection(
        hostname=conn_info.hostname,
        userid=conn_info.username,
        password=conn_info.password,
        virtual_host=conn_info.path,
        port=conn_info.port,
    )
    try:
        connection.ensure_connection(
            errback=_handle_connection_error,
            **_kombu_configuration(cfg))
    except (connection.connection_errors):
        LOG.exception('Error establishing connection, '
                      'shutting down...')
        raise RuntimeError("Error establishing connection to broker.")
    channel = connection.channel()

    # The notifications coming from neutron.
    notifications_exchange = kombu.entity.Exchange(
        name=notifications_exchange_name,
        type='topic',
        durable=False,
        auto_delete=False,
        internal=False,
        channel=channel,
    )

    # The RPC instructions coming from neutron.
    agent_exchange = kombu.entity.Exchange(
        name=rpc_exchange_name,
        type='fanout',
        durable=False,
        auto_delete=True,
        internal=False,
        channel=channel,
    )

    queues = [
        kombu.entity.Queue(
            'akanda.notifications',
            exchange=notifications_exchange,
            routing_key='notifications.*',
            channel=channel,
            durable=False,
            auto_delete=False,
        ),
        kombu.entity.Queue(
            'akanda.l3_agent',
            exchange=agent_exchange,
            routing_key='l3_agent',
            channel=channel,
            durable=False,
            auto_delete=False,
        ),
        kombu.entity.Queue(
            'akanda.l3_agent.' + host_id,
            exchange=agent_exchange,
            routing_key='l3_agent.' + host_id,
            channel=channel,
            durable=False,
            auto_delete=False,
        ),
        kombu.entity.Queue(
            'akanda.dhcp_agent',
            exchange=agent_exchange,
            routing_key='dhcp_agent',
            channel=channel,
            durable=False,
            auto_delete=False,
        ),
        kombu.entity.Queue(
            'akanda.dhcp_agent.' + host_id,
            exchange=agent_exchange,
            routing_key='dhcp_agent.' + host_id,
            channel=channel,
            durable=False,
            auto_delete=False,
        ),
    ]
    for q in queues:
        LOG.debug('setting up queue %s', q)
        q.declare()

    def _process_message(body, message):
        "Send the message through the notification queue"
        # LOG.debug('received %r', body)
        # TODO:
        #  1. Ignore notification messages that we don't care about.
        #  2. Convert notification and rpc messages to a common format
        #     so the lower layer does not have to understand both
        try:
            event = _make_event_from_message(body)
            if event:
                LOG.debug('received message for %s', event.tenant_id)
                notification_queue.put((event.tenant_id, event))
        except:
            LOG.exception('could not process message: %s' % unicode(body))
            message.reject()
        else:
            message.ack()

    consumer = kombu.messaging.Consumer(channel, queues)
    consumer.register_callback(_process_message)
    consumer.consume()

    while True:
        try:
            connection.drain_events()
        except (KeyboardInterrupt, SystemExit):
            LOG.info('Caught exit signal, exiting...')
            break
        except socket.timeout:
            LOG.info('Socket connection timed out, retrying connection')
            try:
                connection.ensure_connection(errback=_handle_connection_error,
                                             **_kombu_configuration(cfg))
            except (connection.connection_errors):
                LOG.exception('Unable to re-establish connection, '
                              'shutting down...')
                break
            else:
                continue
        except:
            LOG.exception('Unhandled exception while draining events from '
                          'queue')
            time.sleep(1)

    connection.release()


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
