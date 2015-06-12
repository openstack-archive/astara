
import threading

import oslo_messaging
from oslo_log import log as logging

# XXX get this from the appropriate config settings. may need
# to provide some mapping from the existing amqp_url to oslo.messaging
# form, for backward comapt?
amqp_url = 'rabbit://stackrabbit:secretrabbit@127.0.0.1:5672/'

from oslo.config import cfg

HOST = 'trusty'
NOTIFICATIONS_EXCHANGE = 'neutron'

LOG = logging.getLogger(__name__)


def get_transport():
    return oslo_messaging.get_transport(conf=cfg.CONF, url=amqp_url)


def get_server(target, endpoints):
    return oslo_messaging.get_rpc_server(
        transport=get_transport(),
        target=target,
        endpoints=endpoints,
    )


def get_target(topic, fanout=True, exchange=None, version=None, server=None):
    return oslo_messaging.Target(
        topic=topic, fanout=fanout, exchange=exchange, version=None,
        server=server)


class Connection(object):
    """Used to create objects that can manage multiple RPC connections"""
    def __init__(self):
        super(Connection, self).__init__()
        self._server_threads = {}

    def _add_server_thread(self, server):
        self._server_threads[server] = threading.Thread(target=server.start)

    def create_rpc_consumer(self, topic, endpoints):
        """Creates an RPC server for this host that will execute RPCs requested
        by clients.
        :param topic: Topic on which to listen for RPC requests
        :param endpoints: List of endpoint objects that define methods that
                          the server will execute.
        """
        target = get_target(topic=topic, fanout=True, server=cfg.CONF.host)
        server = get_server(target, endpoints)
        LOG.debug('Created RPC server on topic %s' % topic)
        self._add_server_thread(server)

    def create_notification_listener(self, endpoints, exchange=None,
                                     topic='notifications'):
        """Creates an oslo.messaging notificatino listener associated with
        provided endpoints

        :param endpoints: list of endpoint objects that define methods for
                          processing prioritized notifications
        :param exchange: Optional control exchange to listen on. If not
                         specified, oslo_messaging defaults to 'openstack'
        :param topic: Topic on which to listen for notification events
        """
        transport = get_transport()
        target = get_target(topic='notifications', fanout=False,
                            exchange=exchange)
        pool = 'akanda.' + topic
        server = oslo_messaging.get_notification_listener(
            transport, [target], endpoints, pool=pool)
        LOG.debug(
            'Created RPC notification listener on topic:%s/exchange:%s.' %
            (topic, exchange))
        self._add_server_thread(server)

    def consume_in_threads(self):
        """Start all RPC consumers in threads"""
        for server, thread in self._server_threads.items():
            LOG.debug('Started RPC connection thread:%s/server:%s' %
                      (thread, server))
            thread.start()

    def close(self):
        for server, thread in self._server_threads.items():
            thread.join()


def get_rpc_client(topic, exchange, version='1.0'):
    """Creates an RPC client to be used to request methods be
    executed on remote RPC servers
    """
    target = get_target(topic=topic, exchange=exchange,
                        version=version, fanout=False)
    return oslo_messaging.rpc.client.RPCClient(
        get_transport(), target
    )


def get_rpc_notifier(topic='notifications'):
    return oslo_messaging.notify.Notifier(
        transport=get_transport(),
        # TODO(adam_g): driver should be specified in oslo.messaging's cfg
        driver='messaging',
        topic=topic,
    )
