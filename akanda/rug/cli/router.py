"""Commands related to routers.
"""
import logging

from akanda.rug import commands
from akanda.rug.cli import message


class _RouterCmd(message.MessageSending):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        p = super(_RouterCmd, self).get_parser(prog_name)
        p.add_argument(
            'router_id',
        )
        return p

    def make_message(self, parsed_args):
        self.log.info(
            'sending %s instruction for router with uuid %r',
            self._COMMAND,
            parsed_args.router_id,
        )
        return {
            'command': self._COMMAND,
            'router_id': parsed_args.router_id,
        }


class RouterDebug(_RouterCmd):
    """debug a single router"""

    _COMMAND = commands.ROUTER_DEBUG


class RouterManage(_RouterCmd):
    """manage a single router"""

    _COMMAND = commands.ROUTER_MANAGE
