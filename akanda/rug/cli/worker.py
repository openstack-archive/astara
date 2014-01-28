"""Commands related to workers.
"""
import logging

from akanda.rug.cli import message


class WorkerDebug(message.MessageSending):
    """debug all workers"""

    log = logging.getLogger(__name__)

    def make_message(self, parsed_args):
        self.log.info(
            'sending worker debug instruction',
        )
        return {
            'command': 'debug workers',
        }
