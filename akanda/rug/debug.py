# Copyright 2014 DreamHost, LLC
#
# Author: DreamHost, LLC
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


import logging
import os
import sys

from oslo_config import cfg

from akanda.rug import state
from akanda.rug import worker


DEBUG_OPTS = [
    cfg.StrOpt(
        'router-id', required=True,
        help='The UUID for the router to debug'),
]

if not hasattr(cfg.CONF, 'host'):
    DEBUG_OPTS.append(cfg.StrOpt('host', default='localhost'))
if not hasattr(cfg.CONF, 'neutron_control_exchange'):
    DEBUG_OPTS.append(cfg.StrOpt('neutron_control_exchange'))
if not hasattr(cfg.CONF, 'amqp_url'):
    DEBUG_OPTS.append(cfg.StrOpt('amqp_url', default='localhost'))


class Fake(object):
    def __init__(self, crud):
        self.crud = crud


def delete_callback(self):
    print 'DELETE'


def bandwidth_callback(self, *args, **kwargs):
    print 'BANDWIDTH:', args, kwargs


def debug_one_router(args=sys.argv[1:]):
    cfg.CONF.register_cli_opts(DEBUG_OPTS)

    # force the config file while in debug
    args.extend(['--config-file', '/etc/akanda-rug/rug.ini'])

    cfg.CONF(args, project='akanda-rug')

    cfg.CONF.register_opts(DEBUG_OPTS)

    cfg.CONF.set_override('boot_timeout', 60000)

    logging.basicConfig(
        level=logging.DEBUG,
        format=':'.join('%(' + n + ')s'
                        for n in ['processName',
                                  'threadName',
                                  'name',
                                  'levelname',
                                  'message']),
    )

    log = logging.getLogger(__name__)
    log.debug('Proxy settings: %r', os.getenv('no_proxy'))

    context = worker.WorkerContext()

    router_obj = context.neutron.get_router_detail(cfg.CONF.router_id)

    a = state.Automaton(
        router_id=cfg.CONF.router_id,
        tenant_id=router_obj.tenant_id,
        delete_callback=delete_callback,
        bandwidth_callback=bandwidth_callback,
        worker_context=context,
        queue_warning_threshold=100,
        reboot_error_threshold=1,
    )

    a.send_message(Fake('update'))

    import pdb
    pdb.set_trace()

    a.update(context)
