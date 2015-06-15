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

from oslo.config import cfg

from akanda.rug.openstack.common import log

LOG = log.getLogger(__name__)


def parse_config(argv, default_config_files=None):
    # Set the logging format to include the process and thread, since
    # those aren't included in standard openstack logs but are useful
    # for the rug
    log_format = ':'.join('%(' + n + ')s'
                          for n in ['asctime',
                                    'levelname',
                                    'name',
                                    'process',
                                    'processName',
                                    'threadName',
                                    'message'])
    cfg.set_defaults(log.logging_cli_opts, log_format=log_format)

    # Configure the default log levels for some third-party packages
    # that are chatty
    cfg.set_defaults(
        log.log_opts,
        default_log_levels=[
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
        ],
    )
    cfg.CONF(argv,
             project='akanda-rug',
             default_config_files=default_config_files)
