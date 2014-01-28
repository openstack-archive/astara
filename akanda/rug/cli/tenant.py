"""Commands related to tenants.
"""
import logging

from akanda.rug import commands
from akanda.rug.cli import message


class _TenantCmd(message.MessageSending):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        p = super(_TenantCmd, self).get_parser(prog_name)
        p.add_argument(
            'tenant_id',
        )
        return p

    def make_message(self, parsed_args):
        self.log.info(
            'sending %s instruction for tenant with uuid %r',
            self._COMMAND,
            parsed_args.tenant_id,
        )
        return {
            'command': self._COMMAND,
            'tenant_id': parsed_args.tenant_id,
        }


class TenantDebug(_TenantCmd):
    """debug a single tenant"""

    _COMMAND = commands.TENANT_DEBUG


class TenantManage(_TenantCmd):
    """manage a single tenant"""

    _COMMAND = commands.TENANT_MANAGE
