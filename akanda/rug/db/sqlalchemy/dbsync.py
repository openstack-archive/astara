# Copyright 2012 New Dream Network, LLC (DreamHost)
# Copyright 2015 Akanda, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import six

from alembic import command as alembic_command
from alembic import config as alembic_config
from alembic import environment
from alembic import script as alembic_script
from alembic import util as alembic_util
from oslo_config import cfg
from oslo_utils import importutils

from akanda.rug.common.i18n import _



_db_opts = [
    cfg.StrOpt('connection',
               deprecated_name='sql_connection',
               default='',
               secret=True,
               help=_('URL to database')),
    cfg.StrOpt('engine',
               default='',
               help=_('Database engine')),
]

CONF = cfg.CONF


def do_alembic_command(config, cmd, *args, **kwargs):
    try:
        getattr(alembic_command, cmd)(config, *args, **kwargs)
    except alembic_util.CommandError as e:
        alembic_util.err(six.text_type(e))


def add_alembic_subparser(sub, cmd):
    return sub.add_parser(cmd, help=getattr(alembic_command, cmd).__doc__)


def do_upgrade(config, cmd):
    revision = CONF.command.revision or 'head'
    do_alembic_command(config, cmd, revision, sql=CONF.command.sql)


def do_stamp(config, cmd):
    do_alembic_command(config, cmd,
                       CONF.command.revision,
                       sql=CONF.command.sql)


def do_revision(config, cmd):
    do_alembic_command(config, cmd,
                       message=CONF.command.message,
                       autogenerate=CONF.command.autogenerate,
                       sql=CONF.command.sql)
    update_head_file(config)



def update_head_file(config):
    script = alembic_script.ScriptDirectory.from_config(config)
    if len(script.get_heads()) > 1:
        alembic_util.err(_('Timeline branches unable to generate timeline'))

    head_path = os.path.join(script.versions, HEAD_FILENAME)
    with open(head_path, 'w+') as f:
        f.write(script.get_current_head())


def add_command_parsers(subparsers):
    for name in ['current', 'history', 'branches']:
        parser = add_alembic_subparser(subparsers, name)
        parser.set_defaults(func=do_alembic_command)

    parser = add_alembic_subparser(subparsers, 'upgrade')
    parser.add_argument('--delta', type=int)
    parser.add_argument('--sql', action='store_true')
    parser.add_argument('revision', nargs='?')
    parser.add_argument('--mysql-engine',
                        default='',
                        help='Change MySQL storage engine of current '
                             'existing tables')
    parser.set_defaults(func=do_upgrade)

    parser = add_alembic_subparser(subparsers, 'stamp')
    parser.add_argument('--sql', action='store_true')
    parser.add_argument('revision')
    parser.set_defaults(func=do_stamp)

    parser = add_alembic_subparser(subparsers, 'revision')
    parser.add_argument('-m', '--message')
    parser.add_argument('--autogenerate', action='store_true')
    parser.add_argument('--sql', action='store_true')
    parser.set_defaults(func=do_revision)


command_opt = cfg.SubCommandOpt('command',
                                title='Command',
                                help=_('Available commands'),
                                handler=add_command_parsers)

CONF.register_cli_opt(command_opt)


def get_alembic_config():
    config = alembic_config.Config(os.path.join(os.path.dirname(__file__),
                                                'alembic.ini'))
    return config


def main():
    CONF(project='akanda-rug')
    config = get_alembic_config()
    config.akanda_config = CONF

    #TODO(gongysh) enable logging
    CONF.command.func(config, CONF.command.name)
