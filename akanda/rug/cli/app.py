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

import pkg_resources

from oslo_config import cfg

from akanda.rug import main


class RugController(app.App):

    log = logging.getLogger(__name__)

    def __init__(self):
        dist = pkg_resources.get_distribution('akanda-rug')
        super(RugController, self).__init__(
            description='controller for the Akanda RUG service',
            version=dist.version,
            command_manager=commandmanager.CommandManager('akanda.rug.cli'),
        )

    def initialize_app(self, argv):
        # Quiet logging for some request library
        logging.getLogger('requests').setLevel(logging.WARN)
        try:
            main.register_and_load_opts()
        except cfg.ArgsAlreadyParsedError:
            pass
        # Don't pass argv here because cfg.CONF will intercept the
        # help options and exit.
        cfg.CONF(['--config-file', '/etc/akanda-rug/rug.ini'],
                 project='akanda-rug')
        self.rug_ini = cfg.CONF
        return super(RugController, self).initialize_app(argv)
