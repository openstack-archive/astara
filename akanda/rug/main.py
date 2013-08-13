import functools
import logging
import multiprocessing
import socket
import sys

from oslo.config import cfg

from akanda.rug import notifications
from akanda.rug import scheduler
from akanda.rug import worker

LOG = logging.getLogger(__name__)


def shuffle_notifications(notification_queue, sched):
    """Copy messages from the notification queue into the scheduler.
    """
    while True:
        try:
            target, message = notification_queue.get()
            sched.handle_message(target, message)
        except KeyboardInterrupt:
            sched.stop()
            break


def main(argv=sys.argv[1:]):
    cfg.CONF.register_opts([
        cfg.StrOpt('host',
                   default=socket.getfqdn(),
                   help="The hostname Akanda is running on"),
    ])
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
        cfg.StrOpt('amqp-url',
                   default='amqp://guest:secrete@localhost:5672/',
                   help='connection for AMQP server'),
    ])
    cfg.CONF(argv, project='akanda')
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(processName)s:%(name)s:%(levelname)s:%(message)s',
    )

    # Set up the queue to move messages between the eventlet-based
    # listening process and the scheduler.
    notification_queue = multiprocessing.Queue()

    # Listen for notifications.
    notification_proc = multiprocessing.Process(
        target=notifications.listen,
        args=(cfg.CONF.host, cfg.CONF.amqp_url, notification_queue,),
        name='NotificationListener',
    )
    notification_proc.start()
    # notifications.listen(amqp_url, notification_queue)

    # Set up a factory to make Workers that know how many threads to
    # run.
    worker_factory = functools.partial(
        worker.Worker,
        num_threads=cfg.CONF.num_worker_threads,
    )

    # Set up the scheduler that knows how to manage the routers and
    # dispatch messages.
    sched = scheduler.Scheduler(
        num_workers=cfg.CONF.num_worker_processes,
        worker_factory=worker_factory,
    )

    # Block the main process, copying messages from the notification
    # listener to the scheduler
    shuffle_notifications(notification_queue, sched)

    # Terminate the listening process
    notification_proc.terminate()

    LOG.info('exiting')
