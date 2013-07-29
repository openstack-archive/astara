"""Listen for notifications.
"""

import logging
import urlparse

import kombu
import kombu.connection
import kombu.entity
import kombu.messaging

from akanda.rug.openstack.common.rpc import common as rpc_common

LOG = logging.getLogger(__name__)


def _get_tenant_id_for_message(message):
    # Find the tenant id in the incoming message.
    if 'oslo.message' in message:
        # Unpack the RPC call body and discard the envelope
        message = rpc_common.deserialize_msg(message)
    for key in ['_context_tenant_id', '_context_project_id']:
        if key in message:
            val = message[key]
            # Some notifications have None as the tenant id, but we
            # can't shard on None in the dispatcher, so treat those as
            # invalid.
            if val is not None:
                return val
    raise ValueError('No tenant id found in message')


def listen(host_id, amqp_url, notification_queue):
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
        name='quantum',  # neutron?
        type='topic',
        durable=False,
        auto_delete=False,
        internal=False,
        channel=channel,
    )

    # The RPC instructions coming from quantum/neutron.
    agent_exchange = kombu.entity.Exchange(
        name='l3_agent_fanout',
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
            tenant_id = _get_tenant_id_for_message(body)
            notification_queue.put((tenant_id, body))
        except:
            LOG.exception('could not process message: %s' % unicode(body))
            message.reject()
        else:
            message.ack()
            LOG.debug('received message for %s', tenant_id)

    consumer = kombu.messaging.Consumer(channel, queues)
    consumer.register_callback(_process_message)
    consumer.consume()

    while True:
        connection.drain_events()
