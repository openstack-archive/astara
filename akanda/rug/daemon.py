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


"""Utilities for managing ourselves as a daemon.
"""

import signal

from oslo_log import log as logging


def ignore_signals():
    """Ignore signals that might interrupt processing

    Since the RUG doesn't want to be asynchronously interrupted,
    various signals received needs to be ignored. The registered
    signals including SIGHUP, SIGALRM, and default signals
    SIGUSR1 and SIGUSR2 are captured and ignored through the SIG_IGN
    action.

    :param: None

    :returns: None

    """
    for s in [signal.SIGHUP, signal.SIGUSR1, signal.SIGUSR2, signal.SIGALRM]:
        logging.getLogger(__name__).info('ignoring signal %s', s)
        signal.signal(s, signal.SIG_IGN)
