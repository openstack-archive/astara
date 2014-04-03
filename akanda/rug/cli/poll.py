"""Commands related to tenants.
"""
import logging

from akanda.rug import commands
from akanda.rug.cli import message


class Poll(message.MessageSending):

    log = logging.getLogger(__name__)

    def make_message(self, parsed_args):
        self.log.info(
            'sending %s instruction',
            commands.POLL,
        )
        return {
            'command': commands.POLL,
        }
