# Copyright 2015 Akanda, Inc
#
# Author: Akanda, Inc
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

import threading
from six.moves.urllib import parse as urlparse

from oslo_log import log as logging
from oslo_config import cfg
import oslo_messaging

from astara.common.i18n import _LW

LOG = logging.getLogger(__name__)


def _deprecated_amqp_url():
    """Allow for deprecating amqp_url setting over time.
    This warns and attempts to translate an amqp_url to something
    oslo_messaging can use to load a driver.
    """
    url = cfg.CONF.amqp_url
    if not url:
        return
    LOG.warning(_LW(
        'Use of amqp_url is deprecated. Please instead use options defined in '
        'oslo_messaging_rabbit to declare your AMQP connection.'))
    url = urlparse.urlsplit(url)
    if url.scheme == 'amqp':
        scheme = 'rabbit'
    else:
        scheme = url.scheme
    port = str(url.port or 5672)
    netloc = url.netloc
    if netloc.endswith(':'):
        netloc = netloc[:-1]
    out = urlparse.urlunsplit((
        scheme,
        '%s:%s' % (netloc, port),
        url.path,
        '', ''
    ))
    return out


def get_transport():
    url = _deprecated_amqp_url()
    return oslo_messaging.get_transport(conf=cfg.CONF, url=url)


def get_server(target, endpoints):
    return oslo_messaging.get_rpc_server(
        transport=get_transport(),
        target=target,
        endpoints=endpoints,
    )


def get_target(topic, fanout=True, exchange=None, version=None, server=None):
    return oslo_messaging.Target(
        topic=topic, fanout=fanout, exchange=exchange, version=version,
        server=server)


def get_rpc_client(topic, exchange=None, version='1.0'):
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


class Connection(object):
    """Used to create objects that can manage multiple RPC connections"""
    def __init__(self):
        super(Connection, self).__init__()
        self._server_threads = {}

    def _add_server_thread(self, server):
        self._server_threads[server] = threading.Thread(target=server.start)

    def create_rpc_consumer(self, topic, endpoints):
        """Creates an RPC server for this host that will execute RPCs requested
        by clients.  Adds the resulting consumer to the pool of RPC server
        threads.

        :param topic: Topic on which to listen for RPC requests
        :param endpoints: List of endpoint objects that define methods that
                          the server will execute.
        """
        target = get_target(topic=topic, fanout=True, server=cfg.CONF.host)
        server = get_server(target, endpoints)
        LOG.debug('Created RPC server on topic %s', topic)
        self._add_server_thread(server)

    def create_notification_listener(self, endpoints, exchange=None,
                                     topic='notifications'):
        """Creates an oslo.messaging notification listener associated with
        provided endpoints. Adds the resulting listener to the pool of RPC
        server threads.

        :param endpoints: list of endpoint objects that define methods for
                          processing prioritized notifications
        :param exchange: Optional control exchange to listen on. If not
                         specified, oslo_messaging defaults to 'openstack'
        :param topic: Topic on which to listen for notification events
        """
        transport = get_transport()
        target = get_target(topic=topic, fanout=False,
                            exchange=exchange)
        pool = 'astara.' + topic + '.' + cfg.CONF.host
        server = oslo_messaging.get_notification_listener(
            transport, [target], endpoints, pool=pool)
        LOG.debug(
            'Created RPC notification listener on topic:%s/exchange:%s.',
            topic, exchange)
        self._add_server_thread(server)

    def consume_in_threads(self):
        """Start all RPC consumers in threads"""
        for server, thread in self._server_threads.items():
            LOG.debug('Started RPC connection thread:%s/server:%s',
                      thread, server)
            thread.start()

    def close(self):
        for server, thread in self._server_threads.items():
            thread.join()
