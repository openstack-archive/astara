"""Utilities for managing ourselves as a daemon.
"""

import signal


def ignore_signals():
    """Ignore signals that might interrupt processing.
    """
    for s in [signal.SIGHUP, signal.SIGUSR1, signal.SIGUSR2, signal.SIGALRM]:
        signal.signal(s, signal.SIG_IGN)
