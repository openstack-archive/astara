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
        context
    )

    a.send_message(Fake('update'))

    import pdb
    pdb.set_trace()

    a.update(worker.WorkerContext())
