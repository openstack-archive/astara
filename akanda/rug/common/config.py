# Copyright 2015 Akanda, Inc.
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

import os

from oslo_config import cfg
from oslo_log import log


LOG = log.getLogger(__name__)

PREFERRED_CONFIG_FILEPATH = '/etc/astara/orchestrator.ini'
SEARCH_DIRS = ['/etc/astara', '/etc/akanda-rug', '/etc/akanda']
LEGACY_FILE_MAP = {
    'orchestrator.ini': 'rug.ini',
    'astara.pub': 'akanda.pub'
    }

DEFAULT_CONFIG_FILES = [
    PREFERRED_CONFIG_FILEPATH
]


def get_best_config_path(filepath=PREFERRED_CONFIG_FILEPATH):
    if os.path.isfile(filepath):
        return filepath

    # now begin attemp to fallback for compatibility
    dirname, basename = os.path.split(filepath)

    if dirname and dirname not in SEARCH_DIRS:
        return filepath  # retain the non-standard location

    for searchdir in SEARCH_DIRS:
        candidate_path = os.path.join(searchdir, basename)
        if os.path.isfile(candidate_path):
            return candidate_path

        if basename in LEGACY_FILE_MAP:
            candidate_path = os.path.join(searchdir, LEGACY_FILE_MAP[basename])
            if os.path.isfile(candidate_path):
                return candidate_path
    return filepath


def parse_config(argv, default_config_files=DEFAULT_CONFIG_FILES):
    log.register_options(cfg.CONF)
    # Set the logging format to include the process and thread, since
    # those aren't included in standard openstack logs but are useful
    # for the rug
    extended = ':'.join('%(' + n + ')s'
                        for n in ['name',
                                  'process',
                                  'processName',
                                  'threadName'])
    log_format = ('%(asctime)s.%(msecs)03d %(levelname)s ' +
                  extended + ' %(message)s')

    # Configure the default log levels for some third-party packages
    # that are chatty
    log_levels = [
        'amqp=WARN',
        'amqplib=WARN',
        'qpid.messaging=INFO',
        'sqlalchemy=WARN',
        'keystoneclient=INFO',
        'stevedore=INFO',
        'eventlet.wsgi.server=WARN',
        'requests=WARN',
        'akanda.rug.openstack.common.rpc.amqp=INFO',
        'neutronclient.client=INFO',
        'oslo.messaging=INFO',
        'iso8601=INFO',
        'cliff.commandmanager=INFO',
    ]
    cfg.CONF.set_default('logging_default_format_string', log_format)
    log.set_defaults(default_log_levels=log_levels)

    # For legacy compatibility
    default_config_files = map(get_best_config_path, default_config_files)

    cfg.CONF(argv,
             project='astara-orchestrator',
             default_config_files=default_config_files)
