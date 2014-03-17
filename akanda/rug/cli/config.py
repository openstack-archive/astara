"""Commands related to the application configuration
"""
import logging

from akanda.rug import commands
from akanda.rug.cli import message


class ConfigReload(message.MessageSending):
    """reload the configuration file(s)"""

    log = logging.getLogger(__name__)

    def make_message(self, parsed_args):
        self.log.info(
            'sending config reload instruction',
        )
        return {
            'command': commands.CONFIG_RELOAD,
        }
