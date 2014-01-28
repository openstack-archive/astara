"""Listen for notifications.
"""

import logging
import Queue
import urlparse
import threading
import uuid

import kombu
import kombu.connection
import kombu.entity
import kombu.messaging

from akanda.rug import event

from akanda.rug.openstack.common import context
from akanda.rug.openstack.common.rpc import common as rpc_common

LOG = logging.getLogger(__name__)


def _get_tenant_id_for_message(message):
    """Find the tenant id in the incoming message."""

    # give priority to the tenant_id in the router dict if one
    # exists in the message
    payload = message.get('payload', {})

    for key in ('router', 'port', 'subnet'):
        if key in payload and payload[key].get('tenant_id'):
            return payload[key]['tenant_id']

    for key in ['_context_tenant_id', '_context_project_id']:
        if key in message:
            val = message[key]
            # Some notifications have None as the tenant id, but we
            # can't shard on None in the dispatcher, so treat those as
            # invalid.
            if val is not None:
                return val
    raise ValueError('No tenant id found in message')


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
        if event_type == 'router.create.end':
            crud = event.CREATE
        elif event_type == 'router.delete.end':
            crud = event.DELETE
        elif event_type in _INTERESTING_NOTIFICATIONS:
            crud = event.UPDATE
        elif event_type.endswith('.end'):
            crud = event.UPDATE
        elif event_type.startswith('akanda.'):
            # Silently ignore notifications we send ourself
            return None
        else:
            # LOG.debug('ignoring message %r', message)
            return None
    return event.Event(tenant_id, router_id, crud, message)


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
    connection.connect()
    channel = connection.channel()

    # The notifications coming from quantum/neutron.
    notifications_exchange = kombu.entity.Exchange(
        name=notifications_exchange_name,
        type='topic',
        durable=False,
        auto_delete=False,
        internal=False,
        channel=channel,
    )

    # The RPC instructions coming from quantum/neutron.
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
        #LOG.debug('received %r', body)
        # TODO:
        #  1. Ignore notification messages that we don't care about.
        #  2. Convert notification and rpc messages to a common format
        #     so the lower layer does not have to understand both
        try:
            event = _make_event_from_message(body)
            if not event:
                return
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
        except KeyboardInterrupt:
            break

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
