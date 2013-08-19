"""Periodic health check code.
"""

import logging
import threading
import time

from akanda.rug import event

LOG = logging.getLogger(__name__)


def _health_inspector(period, scheduler):
    """Runs in the thread.
    """
    while True:
        time.sleep(period)
        LOG.debug('waking up')
        e = event.Event(
            tenant_id='*',
            router_id='*',
            crud=event.POLL,
            body={},
        )
        scheduler.handle_message('*', e)


def start_inspector(period, scheduler):
    """Start a health check thread.
    """
    t = threading.Thread(
        target=_health_inspector,
        args=(period, scheduler,),
        name='HealthInspector',
    )
    t.setDaemon(True)
    t.start()
    return t
