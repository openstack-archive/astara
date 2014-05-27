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

from oslo.config import cfg

from akanda.rug import main
from akanda.rug import state
from akanda.rug import worker


class Fake(object):
    def __init__(self, crud):
        self.crud = crud


def delete_callback(self):
    print 'DELETE'


def bandwidth_callback(self, *args, **kwargs):
    print 'BANDWIDTH:', args, kwargs


def debug_one_router(args=sys.argv[1:]):

    main.register_and_load_opts()

    # Add our extra option for specifying the router-id to debug
    cfg.CONF.register_cli_opts([
        cfg.StrOpt('router-id',
                   required=True,
                   help='The UUID for the router to debug',
                   ),
    ])
    cfg.CONF(args, project='akanda-rug')

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
        cfg.CONF.router_id,
        router_obj.tenant_id,
        delete_callback,
        bandwidth_callback,
        context,
        100
    )

    a.send_message(Fake('update'))

    import pdb
    pdb.set_trace()

    a.update(worker.WorkerContext())
