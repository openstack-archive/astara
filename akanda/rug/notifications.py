"""Listen for notifications.
"""

import logging
import urlparse
import uuid

import kombu
import kombu.connection
import kombu.entity
import kombu.messaging

LOG = logging.getLogger(__name__)


def listen(amqp_url, notification_queue):
    LOG.debug('starting to listen on %s', amqp_url)

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

    exchange = kombu.entity.Exchange(
        name='quantum',  # neutron?
        type='topic',
        durable=False,
        auto_delete=False,
        internal=False,
        channel=channel,
    )

    # TODO(dhellmann): Add an rpc queue here, too.
    queues = [
        kombu.entity.Queue(
            'akanda.notifications',
            exchange=exchange,
            key='notifications.info',
            channel=channel,
            durable=False,
            auto_delete=False,
        ),
    ]
    for q in queues:
        q.declare()

    def _process_message(body, message):
        "Send the message through the notification queue"
        LOG.debug('received %r', body)
        # TODO:
        #  1. Figure out what kind of message the body has
        #     (notification or rpc).
        #  2. Ignore notification messages that we don't care about.
        #  3. Get the router id from the message.
        try:
            # FIXME(dhellmann): Get the router id from the decoded body
            router_id = uuid.UUID('7fe12bca-f3cb-11e2-9084-080027e60b10')
            notification_queue.put((str(router_id), body))
        except:
            LOG.exception('could not process message')
            message.reject()
        else:
            message.ack()

    consumer = kombu.messaging.Consumer(channel, queues)
    consumer.register_callback(_process_message)
    consumer.consume()

    while True:
        connection.drain_events()
