import logging

from cliff import app
from cliff import commandmanager

import pkg_resources

from oslo.config import cfg

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
        main.register_and_load_opts()
        # Don't pass argv here because cfg.CONF will intercept the
        # help options and exit.
        cfg.CONF(['--config-file', '/etc/akanda-rug/rug.ini'],
                 project='akanda-rug')
        self.rug_ini = cfg.CONF
        return super(RugController, self).initialize_app(argv)
