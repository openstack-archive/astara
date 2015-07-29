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

from oslo_config import cfg
from oslo_log import log

from akanda.rug.common.i18n import _, _LE, _LI
from akanda.rug.common import config as ak_cfg
from akanda.rug import daemon
from akanda.rug import health
from akanda.rug import metadata
from akanda.rug import notifications
from akanda.rug import scheduler
from akanda.rug import populate
from akanda.rug import worker
from akanda.rug.api import neutron as neutron_api


LOG = log.getLogger(__name__)
CONF = cfg.CONF

MAIN_OPTS = [
    cfg.StrOpt('host',
               default=socket.getfqdn(),
               help="The hostname Akanda is running on"),
    cfg.BoolOpt('plug_external_port', default=False),
]
CONF.register_opts(MAIN_OPTS)


CEILOMETER_OPTS = [
    cfg.BoolOpt('enabled', default=False,
                help='Enable reporting metrics to ceilometer.'),
    cfg.StrOpt('topic', default='notifications.info',
               help='The name of the topic queue ceilometer consumes events '
                    'from.')
]
CONF.register_group(cfg.OptGroup(name='ceilometer',
                                 title='Ceilometer Reporting Options'))
CONF.register_opts(CEILOMETER_OPTS, group='ceilometer')


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
            LOG.info(_LI('got Ctrl-C'))
            break
        except:
            LOG.exception(_LE('unhandled exception processing message'))


def main(argv=sys.argv[1:]):
    """Main Entry point into the akanda-rug

    This is the main entry point into the akanda-rug. On invocation of
    this method, logging, local network connectivity setup is performed.
    This information is obtained through the 'ak-config' file, passed as
    arguement to this method. Worker threads are spawned for handling
    various tasks that are associated with processing as well as
    responding to different Neutron events prior to starting a notification
    dispatch loop.

    :param argv: list of Command line arguments

    :returns: None

    :raises: None

    """
    # TODO(rama) Error Handling to be added as part of the docstring
    # description

    # Change the process and thread name so the logs are cleaner.

    p = multiprocessing.current_process()
    p.name = 'pmain'
    t = threading.current_thread()
    t.name = 'tmain'
    ak_cfg.parse_config(argv)
    log.setup(cfg.CONF, 'akanda-rug')
    cfg.CONF.log_opt_values(LOG, logging.INFO)

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
        topic=cfg.CONF.ceilometer.topic,
    )

    # Set up a factory to make Workers that know how many threads to
    # run.
    worker_factory = functools.partial(
        worker.Worker,
        notifier=publisher
    )

    # Set up the scheduler that knows how to manage the routers and
    # dispatch messages.
    sched = scheduler.Scheduler(
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
        LOG.info(_LI('stopping processing'))
        sched.stop()
        # Terminate the listening process
        LOG.debug(_('stopping %s'), notification_proc.name)
        notification_proc.terminate()
        LOG.debug(_('stopping %s'), metadata_proc.name)
        metadata_proc.terminate()
        LOG.info(_LI('exiting'))
