import functools
import logging
import multiprocessing
import socket
import sys

from oslo.config import cfg

from akanda.rug import health
from akanda.rug.openstack.common import log
from akanda.rug import metadata
from akanda.rug import notifications
from akanda.rug import scheduler
from akanda.rug import populate
from akanda.rug import worker
from akanda.rug.api import quantum as quantum_api

LOG = log.getLogger(__name__)


def shuffle_notifications(notification_queue, sched):
    """Copy messages from the notification queue into the scheduler.
    """
    while True:
        try:
            target, message = notification_queue.get()
            sched.handle_message(target, message)
        # FIXME(rods): if a signal arrive during an IO operation an
        # IOError is raised. We catch the exceptions in meantime
        # waiting for a better solution.
        except IOError:
            pass
        except KeyboardInterrupt:
            sched.stop()
            break


def register_and_load_opts():

    # Set the logging format to include the process and thread, since
    # those aren't included in standard openstack logs but are useful
    # for the rug
    log_format = ':'.join('%(' + n + ')s'
                          for n in ['asctime',
                                    'levelname',
                                    'name',
                                    'processName',
                                    'threadName',
                                    'message'])
    cfg.set_defaults(log.logging_cli_opts, log_format=log_format)

    # Configure the default log levels for some third-party packages
    # that are chatty
    cfg.set_defaults(log.log_opts,
                     default_log_levels=['amqplib=WARN',
                                         'qpid.messaging=INFO',
                                         'sqlalchemy=WARN',
                                         'keystoneclient=INFO',
                                         'stevedore=INFO',
                                         'eventlet.wsgi.server=WARN',
                                         'requests=WARN',
                                         ])

    cfg.CONF.register_opts([
        cfg.StrOpt('host',
                   default=socket.getfqdn(),
                   help="The hostname Akanda is running on"),

        # FIXME(dhellmann): Use a separate group for these auth params
        cfg.StrOpt('admin_user'),
        cfg.StrOpt('admin_password', secret=True),
        cfg.StrOpt('admin_tenant_name'),
        cfg.StrOpt('auth_url'),
        cfg.StrOpt('auth_strategy', default='keystone'),
        cfg.StrOpt('auth_region'),

        cfg.StrOpt('management_network_id'),
        cfg.StrOpt('external_network_id'),
        cfg.StrOpt('management_subnet_id'),
        cfg.StrOpt('router_image_uuid'),

        cfg.StrOpt('management_prefix', default='fdca:3ba5:a17a:acda::/64'),
        cfg.IntOpt('akanda_mgt_service_port', default=5000),
        cfg.IntOpt('router_instance_flavor', default=1),

        # needed for plugging locally into management network
        cfg.StrOpt('interface_driver'),
        cfg.StrOpt('ovs_integration_bridge', default='br-int'),
        cfg.BoolOpt('ovs_use_veth', default=False),
        cfg.IntOpt('network_device_mtu'),

        # needed for boot waiting
        cfg.IntOpt('boot_timeout', default=600),
        cfg.IntOpt('max_retries', default=3),
        cfg.IntOpt('retry_delay', default=1),

    ])

    cfg.CONF.register_opts(metadata.metadata_opts)

    AGENT_OPTIONS = [
        cfg.StrOpt('root_helper', default='sudo'),
    ]

    cfg.CONF.register_opts(AGENT_OPTIONS, 'AGENT')

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


def main(argv=sys.argv[1:]):
    register_and_load_opts()
    cfg.CONF(argv, project='akanda')

    log.setup('akanda-rug')
    cfg.CONF.log_opt_values(LOG, logging.INFO)

    # Purge the mgt tap interface on startup
    quantum = quantum_api.Quantum(cfg.CONF)
    #TODO(mark): develop better way restore after machine reboot
    #quantum.purge_management_interface()

    # bring the mgt tap interface up
    quantum.ensure_local_service_port()

    # Set up the queue to move messages between the eventlet-based
    # listening process and the scheduler.
    notification_queue = multiprocessing.Queue()

    # Listen for notifications.
    notification_proc = multiprocessing.Process(
        target=notifications.listen,
        kwargs={
            'host_id': cfg.CONF.host,
            'amqp_url': cfg.CONF.amqp_url,
            'notifications_exchange_name':
            cfg.CONF.incoming_notifications_exchange,
            'rpc_exchange_name': cfg.CONF.rpc_exchange,
            'notification_queue': notification_queue,
        },
        name='notification-listener',
    )
    notification_proc.start()

    mgt_ip_address = quantum_api.get_local_service_ip(cfg.CONF).split('/')[0]
    metadata_proc = multiprocessing.Process(
        target=metadata.serve,
        args=(mgt_ip_address,),
        name='metadata-proxy'
    )
    metadata_proc.start()

    # Set up the notifications publisher
    publisher = notifications.Publisher(
        cfg.CONF.amqp_url,
        exchange_name=cfg.CONF.outgoing_notifications_exchange,
        topic='notifications.info',
    )

    # Set up a factory to make Workers that know how many threads to
    # run.
    worker_factory = functools.partial(
        worker.Worker,
        num_threads=cfg.CONF.num_worker_threads,
        notifier=publisher,
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
    shuffle_notifications(notification_queue, sched)

    # Terminate the listening process
    notification_proc.terminate()
    metadata_proc.terminate()

    LOG.info('exiting')
