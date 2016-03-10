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

"""Proxy requests to Nova's metadata server.

Used by main.py
"""


import hashlib
import hmac
from six.moves.urllib import parse as urlparse
import socket

import eventlet
import eventlet.wsgi
import httplib2
from oslo_config import cfg
import webob
import webob.dec
import webob.exc
import six

from oslo_log import log as logging

from astara.common.i18n import _, _LE, _LI, _LW


LOG = logging.getLogger(__name__)
CONF = cfg.CONF

METADATA_OPTS = [
    cfg.StrOpt('nova_metadata_ip', default='127.0.0.1',
               help="IP address used by Nova metadata server."),
    cfg.IntOpt('nova_metadata_port',
               default=8775,
               help="TCP Port used by Nova metadata server."),
    cfg.IntOpt('astara_metadata_port',
               default=9697,
               help="TCP listening port used by Astara metadata proxy."),
    cfg.StrOpt('neutron_metadata_proxy_shared_secret',
               default='',
               help='Shared secret to sign instance-id request',
               deprecated_name='quantum_metadata_proxy_shared_secret')
]
CONF.register_opts(METADATA_OPTS)


class MetadataProxyHandler(object):

    """The actual handler for proxy requests."""

    @webob.dec.wsgify(RequestClass=webob.Request)
    def __call__(self, req):
        """Inital handler for an incoming `webob.Request`.

        :param req: The webob.Request to handle
        :returns: returns a valid HTTP Response or Error
        """
        try:
            LOG.debug("Request: %s", req)

            instance_id = self._get_instance_id(req)
            if instance_id:
                return self._proxy_request(instance_id, req)
            else:
                return webob.exc.HTTPNotFound()

        except Exception:
            LOG.exception(_LE("Unexpected error."))
            msg = ('An unknown error has occurred. '
                   'Please try your request again.')
            return webob.exc.HTTPInternalServerError(
                explanation=six.text_type(msg))

    def _get_instance_id(self, req):
        """Pull the X-Instance-ID out of a request.

        :param req: The webob.Request to handle
        :returns: returns the X-Instance-ID HTTP header
        """
        return req.headers.get('X-Instance-ID')

    def _proxy_request(self, instance_id, req):
        """Proxy a signed HTTP request to an instance.

        :param instance_id: ID of the Instance being proxied to
        :param req: The webob.Request to handle
        :returns: returns a valid HTTP Response or Error
        """
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
            msg = _LW(
                'The remote metadata server responded with Forbidden. This '
                'response usually occurs when shared secrets do not match.'
            )
            LOG.warning(msg)
            return webob.exc.HTTPForbidden()
        elif resp.status == 404:
            return webob.exc.HTTPNotFound()
        elif resp.status == 500:
            msg = _LW('Remote metadata server experienced an'
                      ' internal server error.')
            LOG.warning(msg)
            return webob.exc.HTTPInternalServerError(
                explanation=six.text_type(msg))
        else:
            raise Exception(_('Unexpected response code: %s') % resp.status)

    def _sign_instance_id(self, instance_id):
        """Get an HMAC based on the instance_id and Neutron shared secret.

        :param instance_id: ID of the Instance being proxied to
        :returns: returns a hexadecimal string HMAC for a specific instance_id
        """
        return hmac.new(cfg.CONF.neutron_metadata_proxy_shared_secret,
                        instance_id,
                        hashlib.sha256).hexdigest()


class MetadataProxy(object):

    """The proxy service."""

    def __init__(self):
        """Initialize the MetadataProxy.

        :returns: returns nothing
        """
        self.pool = eventlet.GreenPool(1000)

    def run(self, ip_address, port=cfg.CONF.astara_metadata_port):
        """Run the MetadataProxy.

        :param ip_address: the ip address to bind to for incoming requests
        :param port: the port to bind to for incoming requests
        :returns: returns nothing
        """
        app = MetadataProxyHandler()
        for i in six.moves.range(5):
            LOG.info(_LI(
                'Starting the metadata proxy on %s:%s'),
                ip_address, port
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
                LOG.warning(
                    _LW('Could not create metadata proxy socket: %s'), err)
                LOG.warning(_LW('Sleeping %s before trying again'), i + 1)
                eventlet.sleep(i + 1)
            else:
                break
        else:
            raise RuntimeError(
                _('Could not establish metadata proxy socket on %s:%s') %
                (ip_address, port)
            )
        eventlet.wsgi.server(
            sock,
            app,
            custom_pool=self.pool,
            log=LOG)


def serve(ip_address):
    """Initialize the MetaData proxy.

    :param ip_address: the ip address to bind to for incoming requests
    :returns: returns nothing
    """
    MetadataProxy().run(ip_address)
