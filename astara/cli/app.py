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


import logging

from cliff import app
from cliff import commandmanager
from oslo_config import cfg
import pkg_resources

from astara.common import config


class RugController(app.App):

    def __init__(self):
        dist = pkg_resources.get_distribution('astara')
        super(RugController, self).__init__(
            description='controller for the Astara Orchestrator service',
            version=dist.version,
            command_manager=commandmanager.CommandManager('astara.cli'),
        )

    def initialize_app(self, argv):
        # Quiet logging for some request library
        logging.getLogger('requests').setLevel(logging.WARN)

        # Don't pass argv here because cfg.CONF will intercept the
        # help options and exit.
        cfg.CONF(['--config-file', config.get_best_config_path()],
                 project='astara-orchestrator')
        self.rug_ini = cfg.CONF
        return super(RugController, self).initialize_app(argv)
