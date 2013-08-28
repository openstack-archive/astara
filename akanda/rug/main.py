import functools
import logging
import multiprocessing
import signal
import socket
import sys

from oslo.config import cfg

from akanda.rug import event
from akanda.rug import health
from akanda.rug import notifications
from akanda.rug import scheduler
from akanda.rug import populate
from akanda.rug import worker
from akanda.rug.api import quantum as quantum_api

LOG = logging.getLogger(__name__)


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


def main(argv=sys.argv[1:]):
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

        # needed for plugging locally into management network
        cfg.StrOpt('interface_driver'),
        cfg.StrOpt('ovs_integration_bridge', default='br-int'),
        cfg.BoolOpt('ovs_use_veth', default=False),

    ])

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
                   default='quantum',
                   help='name of the exchange where we receive notifications'),
        cfg.StrOpt('outgoing-notifications-exchange',
                   default='quantum',
                   help='name of the exchange where we send notifications'),
        cfg.StrOpt('rpc-exchange',
                   default='l3_agent_fanout',
                   help='name of the exchange where we receive RPC calls'),
    ])
    cfg.CONF(argv, project='akanda')

    logging.basicConfig(
        level=logging.DEBUG,
        format=':'.join('%(' + n + ')s'
                        for n in ['processName',
                                  'threadName',
                                  'name',
                                  'levelname',
                                  'message']),
    )

    # Purge the mgt tap interface on startup
    quantum = quantum_api.Quantum(cfg.CONF)
    quantum.purge_management_interface()

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

    def debug_workers(signum, stack):
        sched.handle_message(
            'debug',
            event.Event('debug', '', event.POLL, {'verbose': 1})
        )

    signal.signal(signal.SIGUSR1, debug_workers)

    # Prepopulate the workers with existing routers on startup
    populate.pre_populate_workers(sched)

    # Set up the periodic health check
    health.start_inspector(cfg.CONF.health_check_period, sched)

    # Block the main process, copying messages from the notification
    # listener to the scheduler
    shuffle_notifications(notification_queue, sched)

    # Terminate the listening process
    notification_proc.terminate()

    # Purge the mgt tap interface
    quantum.purge_management_interface()

    LOG.info('exiting')
