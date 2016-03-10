# Copyright 2015 Akanda, Inc
#
# Author: Akanda, Inc
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

import socket

import eventlet
import eventlet.wsgi
import webob
import webob.dec
import webob.exc
import six

from oslo_config import cfg
from oslo_log import log as logging

from astara.cli import app
from astara.common.i18n import _, _LE, _LI, _LW

LOG = logging.getLogger(__name__)

RUG_API_OPTS = [
    cfg.IntOpt('api_port', default=44250,
               help='Astara administrative API listening port',
               deprecated_opts=[
                    cfg.DeprecatedOpt('rug_api_port',
                                      group='DEFAULT')]),
    cfg.StrOpt('api_listen', default='0.0.0.0',
               help='Astara administrative API listening address')
]
cfg.CONF.register_opts(RUG_API_OPTS)


class RugAPI(object):

    def __init__(self, ctl=app.RugController):
        self.ctl = ctl()

    @webob.dec.wsgify(RequestClass=webob.Request)
    def __call__(self, req):
        try:
            if req.method != 'PUT':
                return webob.exc.HTTPMethodNotAllowed()

            args = filter(None, req.path.split('/'))
            if not args:
                return webob.exc.HTTPNotFound()

            command, _, _ = self.ctl.command_manager.find_command(args)
            if command.interactive:
                return webob.exc.HTTPNotImplemented()

            return str(self.ctl.run(['--debug'] + args))
        except SystemExit:
            # cliff invokes -h (help) on argparse failure
            # (which in turn results in sys.exit call)
            return webob.exc.HTTPBadRequest()
        except ValueError:
            return webob.exc.HTTPNotFound()
        except Exception:
            LOG.exception(_LE("Unexpected error."))
            msg = _('An unknown error has occurred. '
                    'Please try your request again.')
            return webob.exc.HTTPInternalServerError(explanation=six.text_type(msg))


class RugAPIServer(object):
    def __init__(self):
        self.pool = eventlet.GreenPool(1000)

    def run(self, ip_address, port):
        app = RugAPI()

        try:
            socket.inet_pton(socket.AF_INET6, ip_address)
            family = socket.AF_INET6
        except Exception:
            family = socket.AF_INET

        for i in six.moves.range(5):
            LOG.info(_LI(
                'Starting the rug-api on %s:%s'),
                ip_address, port,
            )
            try:
                sock = eventlet.listen(
                    (ip_address, port),
                    family=family,
                    backlog=128
                )
            except socket.error as err:
                if err.errno != 99:  # EADDRNOTAVAIL
                    raise
                LOG.warning(_LW('Could not create rug-api socket: %s'), err)
                LOG.warning(_LW('Sleeping %s before trying again'), i + 1)
                eventlet.sleep(i + 1)
            else:
                break
        else:
            raise RuntimeError(_(
                'Could not establish rug-api socket on %s:%s') %
                (ip_address, port)
            )
        eventlet.wsgi.server(
            sock,
            app,
            custom_pool=self.pool,
            log=LOG)


def serve():
    RugAPIServer().run(cfg.CONF.api_listen, cfg.CONF.api_port)
