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


from __future__ import print_function

import os
import sys

from oslo_config import cfg
from oslo_log import log as logging

from astara import drivers
from astara import state
from astara import worker

from astara.common import config


DEBUG_OPTS = [
    cfg.StrOpt(
        'router-id', required=True,
        help='The UUID for the router to debug')
]


class Fake(object):
    def __init__(self, crud):
        self.crud = crud


def delete_callback(self):
    print('DELETE')


def bandwidth_callback(self, *args, **kwargs):
    print('BANDWIDTH:', args, kwargs)


def debug_one_router(args=sys.argv[1:]):
    # Add our extra option for specifying the router-id to debug
    cfg.CONF.register_cli_opts(DEBUG_OPTS)
    cfg.CONF.set_override('boot_timeout', 60000)
    cfg.CONF.import_opt('host', 'astara.main')
    config.parse_config(args)
    logging.setup(cfg.CONF, __name__)
    log = logging.getLogger(__name__)
    log.debug('Proxy settings: %r', os.getenv('no_proxy'))

    context = worker.WorkerContext()
    driver = drivers.get('router')(context, cfg.CONF.router_id)
    a = state.Automaton(
        driver=driver,
        resource_id=cfg.CONF.router_id,
        tenant_id=driver._router.tenant_id,
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
