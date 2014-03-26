"""Utilities for managing ourselves as a daemon.
"""

import logging
import signal


def ignore_signals():
    """Ignore signals that might interrupt processing.
    """
    for s in [signal.SIGHUP, signal.SIGUSR1, signal.SIGUSR2, signal.SIGALRM]:
        logging.getLogger(__name__).info('ignoring signal %s', s)
        signal.signal(s, signal.SIG_IGN)
