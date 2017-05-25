# Copyright 2015 Akanda, Inc
#
# Author: Akanda, Inc
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

import logging
import sys

from astara.common import config as ak_cfg

from astara.common import rpc
from astara.pez import manager

from oslo_config import cfg
from oslo_log import log
from oslo_service import service

CONF = cfg.CONF

LOG = log.getLogger(__name__)


class PezService(service.Service):
    """Bootstraps a connection for the manager to the messaging
    queue and launches the pez service
    """
    def __init__(self):
        super(PezService, self).__init__()
        self.manager = manager.PezManager()
        self.manager.start()
        self._rpc_connection = None
        self.rpcserver = None

    def start(self):
        super(PezService, self).start()
        self._rpc_connection = rpc.Connection()
        self._rpc_connection.create_rpc_consumer(
            topic=cfg.CONF.pez.rpc_topic,
            endpoints=[self.manager])
        self._rpc_connection.consume_in_threads()
        self._rpc_connection.close()


def main(argv=sys.argv[1:]):
    ak_cfg.parse_config(argv)
    log.setup(CONF, 'astara-pez')
    CONF.log_opt_values(LOG, logging.INFO)

    LOG.info("Starting Astara Pez service.")

    mgr = PezService()
    launcher = service.launch(CONF, mgr)
    launcher.wait()
