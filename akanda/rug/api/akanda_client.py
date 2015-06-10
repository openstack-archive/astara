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


from akanda.rug.common import log_shim as logging
import requests

from oslo.config import cfg
from oslo_serialization import jsonutils

AKANDA_ULA_PREFIX = 'fdca:3ba5:a17a:acda::/64'
AKANDA_MGT_SERVICE_PORT = 5000
AKANDA_BASE_PATH = '/v1/'

LOG = logging.getLogger(__name__)


def _mgt_url(host, port, path):
    if ':' in host:
        host = '[%s]' % host
    return 'http://%s:%s%s' % (host, port, path)


def _get_proxyless_session():
    s = requests.Session()
    # ignore any proxy setting because we should have a direct connection
    s.trust_env = False
    return s


def is_alive(host, port):
    path = AKANDA_BASE_PATH + 'firewall/rules'
    try:
        s = _get_proxyless_session()
        r = s.get(_mgt_url(host, port, path), timeout=cfg.CONF.alive_timeout)
        if r.status_code == 200:
            return True
    except Exception as e:
        LOG.debug('is_alive for %s failed: %s', host, str(e))
    return False


def get_interfaces(host, port):
    path = AKANDA_BASE_PATH + 'system/interfaces'
    s = _get_proxyless_session()
    r = s.get(_mgt_url(host, port, path), timeout=30)
    return r.json().get('interfaces', [])


def update_config(host, port, config_dict):
    path = AKANDA_BASE_PATH + 'system/config'
    headers = {'Content-type': 'application/json'}

    s = _get_proxyless_session()
    r = s.put(
        _mgt_url(host, port, path),
        data=jsonutils.dumps(config_dict),
        headers=headers,
        timeout=cfg.CONF.config_timeout)

    if r.status_code != 200:
        raise Exception('Config update failed: %s' % r.text)
    else:
        return r.json()


def read_labels(host, port):
    path = AKANDA_BASE_PATH + 'firewall/labels'
    s = _get_proxyless_session()
    r = s.post(_mgt_url(host, port, path), timeout=30)
    return r.json().get('labels', [])
