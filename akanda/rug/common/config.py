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

from oslo_config import cfg
from oslo_log import log


LOG = log.getLogger(__name__)

DEFAULT_CONFIG_FILES = [
    '/etc/akanda-rug/rug.ini'
]


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
    cfg.CONF(argv,
             project='akanda-rug',
             default_config_files=default_config_files)
