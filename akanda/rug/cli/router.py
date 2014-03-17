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


class RouterUpdate(_RouterCmd):
    """force-update a router"""

    _COMMAND = commands.ROUTER_UPDATE

    def get_parser(self, prog_name):
        # Bypass the direct base class to let us put the tenant id
        # argument first
        p = super(_RouterCmd, self).get_parser(prog_name)
        p.add_argument(
            'tenant_id',
        )
        p.add_argument(
            'router_id',
            nargs='?',
        )
        return p

    def make_message(self, parsed_args):
        tenant_id = parsed_args.tenant_id.replace('-', '')
        tenant_id = '-'.join([
            tenant_id[:8],
            tenant_id[8:12],
            tenant_id[12:16],
            tenant_id[16:20],
            tenant_id[20:],
        ])
        self.log.info(
            'sending %s instruction for tenant %r, router with uuid %r',
            self._COMMAND,
            tenant_id,
            parsed_args.router_id,
        )
        return {
            'command': self._COMMAND,
            'router_id': parsed_args.router_id,
            'tenant_id': tenant_id,
        }
