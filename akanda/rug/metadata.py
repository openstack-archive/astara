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


# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2012 New Dream Network, LLC (DreamHost)
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
#
# @author: Mark McClain, DreamHost

import hashlib
import hmac
import socket
import urlparse

import eventlet
import eventlet.wsgi
import httplib2
from oslo_config import cfg
import webob
import webob.dec
import webob.exc

from oslo_log import log as logging
from oslo_log import loggers


LOG = logging.getLogger(__name__)
CONF = cfg.CONF

RUG_META_PORT = 9697


METADATA_OPTS = [
    cfg.StrOpt('nova_metadata_ip', default='127.0.0.1',
               help="IP address used by Nova metadata server."),
    cfg.IntOpt('nova_metadata_port',
               default=8775,
               help="TCP Port used by Nova metadata server."),
    cfg.StrOpt('neutron_metadata_proxy_shared_secret',
               default='',
               help='Shared secret to sign instance-id request',
               deprecated_name='quantum_metadata_proxy_shared_secret')
]
CONF.register_opts(METADATA_OPTS)


class MetadataProxyHandler(object):

    @webob.dec.wsgify(RequestClass=webob.Request)
    def __call__(self, req):
        try:
            LOG.debug("Request: %s", req)

            instance_id = self._get_instance_id(req)
            if instance_id:
                return self._proxy_request(instance_id, req)
            else:
                return webob.exc.HTTPNotFound()

        except Exception:
            LOG.exception("Unexpected error.")
            msg = ('An unknown error has occurred. '
                   'Please try your request again.')
            return webob.exc.HTTPInternalServerError(explanation=unicode(msg))

    def _get_instance_id(self, req):
        return req.headers.get('X-Instance-ID')

    def _proxy_request(self, instance_id, req):
        headers = {
            'X-Forwarded-For': req.headers.get('X-Forwarded-For'),
            'X-Instance-ID': instance_id,
            'X-Instance-ID-Signature': self._sign_instance_id(instance_id),
            'X-Tenant-ID': req.headers.get('X-Tenant-ID')
        }

        url = urlparse.urlunsplit((
            'http',
            '%s:%s' % (cfg.CONF.nova_metadata_ip,
                       cfg.CONF.nova_metadata_port),
            req.path_info,
            req.query_string,
            ''))

        h = httplib2.Http()
        resp, content = h.request(url, headers=headers)

        if resp.status == 200:
            LOG.debug(str(resp))
            return content
        elif resp.status == 403:
            msg = (
                'The remote metadata server responded with Forbidden. This '
                'response usually occurs when shared secrets do not match.'
            )
            LOG.warning(msg)
            return webob.exc.HTTPForbidden()
        elif resp.status == 404:
            return webob.exc.HTTPNotFound()
        elif resp.status == 500:
            LOG.warning(
                'Remote metadata server experienced an internal server error.'
            )
            return webob.exc.HTTPInternalServerError(explanation=unicode(msg))
        else:
            raise Exception('Unexpected response code: %s' % resp.status)

    def _sign_instance_id(self, instance_id):
        return hmac.new(cfg.CONF.neutron_metadata_proxy_shared_secret,
                        instance_id,
                        hashlib.sha256).hexdigest()


class MetadataProxy(object):
    def __init__(self):
        self.pool = eventlet.GreenPool(1000)

    def run(self, ip_address, port=RUG_META_PORT):
        app = MetadataProxyHandler()
        for i in xrange(5):
            LOG.info(
                'Starting the metadata proxy on %s/%s',
                ip_address, port,
            )
            try:
                sock = eventlet.listen(
                    (ip_address, port),
                    family=socket.AF_INET6,
                    backlog=128
                )
            except socket.error as err:
                if err.errno != 99:
                    raise
                LOG.warning('Could not create metadata proxy socket: %s', err)
                LOG.warning('Sleeping %s before trying again', i + 1)
                eventlet.sleep(i + 1)
            else:
                break
        else:
            raise RuntimeError(
                'Could not establish metadata proxy socket on %s/%s' %
                (ip_address, port)
            )
        eventlet.wsgi.server(
            sock,
            app,
            custom_pool=self.pool,
            log=loggers.WritableLogger(LOG))


def serve(ip_address):
    MetadataProxy().run(ip_address)
