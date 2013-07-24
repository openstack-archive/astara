import logging
import multiprocessing
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
            router_id, message = notification_queue.get()
            sched.handle_message(router_id, message)
        except KeyboardInterrupt:
            sched.stop()
            break


def main(argv=sys.argv[1:]):
    cfg.CONF.register_cli_opts([
        cfg.IntOpt('health-check-period',
                   default=60,
                   help='seconds between health checks'),
        cfg.IntOpt('num-workers',
                   short='n',
                   default=16,
                   help='the number of worker processes to run'),
    ])
    cfg.CONF(argv, project='akanda')
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(processName)s:%(name)s:%(message)s',
    )

    # Set up the queue to move messages between the eventlet-based
    # listening process and the scheduler.
    notification_queue = multiprocessing.Queue()

    # Listen for notifications.
    #
    # TODO(dhellmann): We will need to pass config settings through
    # here, or have the child process reset the cfg.CONF object.
    notifications.listen(notification_queue)

    worker_dispatcher = worker.Worker()

    # Set up the scheduler that knows how to manage the routers and
    # dispatch messages.
    sched = scheduler.Scheduler(
        num_workers=cfg.CONF.num_workers,
        worker_func=worker_dispatcher.handle_message,
    )
    shuffle_notifications(notification_queue,
                          sched,
                          )

    LOG.info('exiting')
