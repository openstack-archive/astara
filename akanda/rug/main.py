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


import functools
import logging
import multiprocessing
import signal
import socket
import sys
import threading

from oslo.config import cfg

from akanda.rug import daemon
from akanda.rug import health
from akanda.rug.openstack.common import log
from akanda.rug import metadata
from akanda.rug import notifications
from akanda.rug import scheduler
from akanda.rug import populate
from akanda.rug import worker
from akanda.rug.api import neutron as neutron_api

LOG = log.getLogger(__name__)


def shuffle_notifications(notification_queue, sched):
    """Copy messages from the notification queue into the scheduler.
    """
    while True:
        try:
            target, message = notification_queue.get()
            if target is None:
                break
            sched.handle_message(target, message)
        except IOError:
            # FIXME(rods): if a signal arrive during an IO operation
            # an IOError is raised. We catch the exceptions in
            # meantime waiting for a better solution.
            pass
        except KeyboardInterrupt:
            LOG.info('got Ctrl-C')
            break
        except:
            LOG.exception('unhandled exception processing message')


def register_and_load_opts():

    # Set the logging format to include the process and thread, since
    # those aren't included in standard openstack logs but are useful
    # for the rug
    log_format = ':'.join('%(' + n + ')s'
                          for n in ['asctime',
                                    'levelname',
                                    'name',
                                    'process',
                                    'processName',
                                    'threadName',
                                    'message'])
    cfg.set_defaults(log.logging_cli_opts, log_format=log_format)

    # Configure the default log levels for some third-party packages
    # that are chatty
    cfg.set_defaults(
        log.log_opts,
        default_log_levels=[
            'amqp=WARN',
            'amqplib=WARN',
            'qpid.messaging=INFO',
            'sqlalchemy=WARN',
            'keystoneclient=INFO',
            'stevedore=INFO',
            'eventlet.wsgi.server=WARN',
            'requests=WARN',
            'akanda.rug.openstack.common.rpc.amqp=INFO',
            'neutronclient.client=INFO',
        ],
    )

    # Options defined in the [DEFAULT] group
    DEFAULT_OPTS = [
        cfg.StrOpt('host',
                   default=socket.getfqdn(),
                   help="The hostname Akanda is running on"),

        # FIXME(dhellmann): Use a separate group for these auth params
        cfg.StrOpt('admin_user',
                   help='Username of the admin service user'),
        cfg.StrOpt('admin_password', secret=True,
                   help='Password for the admin service user'),
        cfg.StrOpt('admin_tenant_name',
                   help='Tenant name of the admin service user'),
        cfg.StrOpt('auth_url',
                   help='The Keystone auth url'),
        cfg.StrOpt('auth_strategy',
                   help='Authentication strategy to be used',
                   default='keystone'),
        cfg.StrOpt('auth_region',
                   help='The region in which to authenticate'),

        cfg.StrOpt('management_network_id',
                   help='Neutron network UUID of the management network'),
        cfg.StrOpt('external_network_id',
                   help='Neutron network UUID of the external network'),
        cfg.StrOpt('management_subnet_id',
                   help='Neutron subnet UUID of the management subnet'),
        cfg.StrOpt('external_subnet_id',
                   help='Neutron subnet UUID of the management subnet'),
        cfg.StrOpt('router_image_uuid',
                   help='UUID of the router appliance image in Glance'),

        cfg.StrOpt('management_prefix', default='fdca:3ba5:a17a:acda::/64',
                   help='Management network IP block'),
        cfg.StrOpt('external_prefix', default='172.16.77.0/24',
                   help='External network IP block'),
        cfg.IntOpt('akanda_mgt_service_port', default=5000,
                   help='Port on which the appliance API server(s) are '
                        'listening'),
        cfg.IntOpt('router_instance_flavor', default=1,
                   help='The nova flavor ID to use for appliance VMs'),

        # needed for plugging locally into management network
        cfg.StrOpt('interface_driver',
                   help='The currently configured Neutron interface driver'),
        cfg.StrOpt('ovs_integration_bridge', default='br-int',
                   help='The name of the local OVS bridge to use'),
        cfg.BoolOpt('ovs_use_veth', default=False,
                    help='Whether to use veth for an interface'),
        cfg.IntOpt('network_device_mtu',
                   help='MTU setting to use on device'),

        cfg.BoolOpt('plug_external_port', default=False,
                    help='Whether to plug into the port locally'),

        cfg.IntOpt('hotplug_timeout', default=10,
                   help='The amount of time to wait for nova to hotplug/unplug'
                        ' networks from the router VM'),

        cfg.IntOpt('boot_timeout', default=600,
                   help='The amount of time to wait for the appliance VMs to '
                        'boot'),
        cfg.IntOpt('max_retries', default=3,
                   help='How many retries to issue on failed API calls to'
                        'external services'),
        cfg.IntOpt('retry_delay', default=1,
                   help='How long to wait between retries'),
        cfg.IntOpt('alive_timeout', default=3,
                   help='How long to wait before determinig a router is '
                        'not alive'),
        cfg.IntOpt('config_timeout', default=90,
                   help='How long to wait for appliance config updates'),

        cfg.StrOpt(
            'ignored_router_directory',
            default='/etc/akanda-rug/ignored',
            help='Directory to scan for routers to ignore for debugging',
        ),

        cfg.IntOpt(
            'queue_warning_threshold',
            default=worker.Worker.QUEUE_WARNING_THRESHOLD_DEFAULT,
            help='warn if the event backlog for a tenant exceeds this value',
        ),

        cfg.IntOpt(
            'reboot_error_threshold',
            default=worker.Worker.REBOOT_ERROR_THRESHOLD_DEFAULT,
            help=('Number of reboots to allow before assuming '
                  'a router needs manual intervention'),
        ),
        cfg.IntOpt(
            'error_state_cooldown',
            default=30,
            help=('Number of seconds to ignore new events when a router goes '
                  'into ERROR state'),
        )
    ]

    # Options defined in the [AGENT] section
    AGENT_OPTS = [
        cfg.StrOpt('root_helper', default='sudo',
                   help='Helper command to use when running commands as root'),
    ]
    # Options defined in the [ceilometer] section
    CEILOMETER_OPTS = [
        cfg.BoolOpt('enabled',
                    default=False,
                    help='Enable reporting metrics to ceilometer.'),
        cfg.StrOpt('topic',
                   default='notifications.info',
                   help='The name of the topic queue ceilometer consumes '
                        'events from.')
    ]

    opt_groups = {
        'DEFAULT': DEFAULT_OPTS + metadata.metadata_opts,
        'AGENT': AGENT_OPTS,
        'ceilometer': CEILOMETER_OPTS,
    }
    for group, opts in opt_groups.items():
        if group == 'DEFAULT':
            group = None
        cfg.CONF.register_opts(opts, group)

    # FIXME: Convert these to regular options, not command line options.
    cfg.CONF.register_cli_opts([
        cfg.IntOpt('health-check-period',
                   default=60,
                   help='seconds between health checks'),
        cfg.IntOpt('num-worker-processes',
                   short='w',
                   default=16,
                   help='the number of worker processes to run'),
        cfg.IntOpt('num-worker-threads',
                   short='t',
                   default=4,
                   help='the number of worker threads to run per process'),

        # FIXME(dhellmann): set up a group for these messaging params
        cfg.StrOpt('amqp-url',
                   default='amqp://guest:secrete@localhost:5672/',
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
    ])

    return [(g, o) for g, o in opt_groups.items()]


def main(argv=sys.argv[1:]):
    # Change the process and thread name so the logs are cleaner.
    p = multiprocessing.current_process()
    p.name = 'pmain'
    t = threading.current_thread()
    t.name = 'tmain'

    register_and_load_opts()
    cfg.CONF(argv, project='akanda-rug')

    log.setup('akanda-rug')
    cfg.CONF.log_opt_values(LOG, logging.INFO)

    # Purge the mgt tap interface on startup
    neutron = neutron_api.Neutron(cfg.CONF)
    # TODO(mark): develop better way restore after machine reboot
    # neutron.purge_management_interface()

    # bring the mgt tap interface up
    neutron.ensure_local_service_port()

    # bring the external port
    if cfg.CONF.plug_external_port:
        neutron.ensure_local_external_port()

    # Set up the queue to move messages between the eventlet-based
    # listening process and the scheduler.
    notification_queue = multiprocessing.Queue()

    # Ignore signals that might interrupt processing.
    daemon.ignore_signals()

    # If we see a SIGINT, stop processing.
    def _stop_processing(*args):
        notification_queue.put((None, None))
    signal.signal(signal.SIGINT, _stop_processing)

    # Listen for notifications.
    notification_proc = multiprocessing.Process(
        target=notifications.listen,
        kwargs={
            'host_id': cfg.CONF.host,
            'amqp_url': cfg.CONF.amqp_url,
            'notifications_exchange_name':
            cfg.CONF.incoming_notifications_exchange,
            'rpc_exchange_name': cfg.CONF.rpc_exchange,
            'notification_queue': notification_queue
        },
        name='notification-listener',
    )
    notification_proc.start()

    mgt_ip_address = neutron_api.get_local_service_ip(cfg.CONF).split('/')[0]
    metadata_proc = multiprocessing.Process(
        target=metadata.serve,
        args=(mgt_ip_address,),
        name='metadata-proxy'
    )
    metadata_proc.start()

    from akanda.rug.api import rug as rug_api
    rug_api_proc = multiprocessing.Process(
        target=rug_api.serve,
        args=(mgt_ip_address,),
        name='rug-api'
    )
    rug_api_proc.start()

    # Set up the notifications publisher
    Publisher = (notifications.Publisher if cfg.CONF.ceilometer.enabled
                 else notifications.NoopPublisher)
    publisher = Publisher(
        cfg.CONF.amqp_url,
        exchange_name=cfg.CONF.outgoing_notifications_exchange,
        topic=cfg.CONF.ceilometer.topic,
    )

    # Set up a factory to make Workers that know how many threads to
    # run.
    worker_factory = functools.partial(
        worker.Worker,
        num_threads=cfg.CONF.num_worker_threads,
        notifier=publisher,
        ignore_directory=cfg.CONF.ignored_router_directory,
        queue_warning_threshold=cfg.CONF.queue_warning_threshold,
        reboot_error_threshold=cfg.CONF.reboot_error_threshold,
    )

    # Set up the scheduler that knows how to manage the routers and
    # dispatch messages.
    sched = scheduler.Scheduler(
        num_workers=cfg.CONF.num_worker_processes,
        worker_factory=worker_factory,
    )

    # Prepopulate the workers with existing routers on startup
    populate.pre_populate_workers(sched)

    # Set up the periodic health check
    health.start_inspector(cfg.CONF.health_check_period, sched)

    # Block the main process, copying messages from the notification
    # listener to the scheduler
    try:
        shuffle_notifications(notification_queue, sched)
    finally:
        # Terminate the scheduler and its workers
        LOG.info('stopping processing')
        sched.stop()
        # Terminate the listening process
        LOG.debug('stopping %s', notification_proc.name)
        notification_proc.terminate()
        LOG.debug('stopping %s', metadata_proc.name)
        metadata_proc.terminate()
        LOG.info('exiting')
