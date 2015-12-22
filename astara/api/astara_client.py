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


import requests
import six
import time

from astara.common.i18n import _, _LE, _LW
from oslo_config import cfg
from astara.common import exception
from oslo_log import log as logging
from oslo_serialization import jsonutils

ASTARA_MGT_SERVICE_PORT = 5000
ASTARA_BASE_PATH = '/v1/'

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

AK_CLIENT_OPTS = [
    cfg.IntOpt('alive_timeout', default=3),
    cfg.IntOpt('config_timeout', default=90),
]
CONF.register_opts(AK_CLIENT_OPTS)


class AstaraAPITooManyAttempts(exception.BaseAstaraException):
    message = _(
        'astara-appliance request failed after %s attempts' %
        cfg.CONF.max_retries)


def retry_on_failure(f):
    def wrapper(*args, **kwargs):
        attempts = cfg.CONF.max_retries
        for i in six.moves.range(attempts):
            try:
                return f(*args, **kwargs)
            except Exception:
                if i == attempts - 1:
                    # Only log the traceback if we encounter it many times.
                    LOG.exception(_LE('failed to update config'))
                else:
                    LOG.warn(_LW(
                        'astara-appliance request failed, attempt %d'), i)
                time.sleep(cfg.CONF.retry_delay)

        raise AstaraAPITooManyAttempts()

    return wrapper


def _mgt_url(host, port, path):
    if ':' in host:
        host = '[%s]' % host
    return 'http://%s:%s%s' % (host, port, path)


def _get_proxyless_session():
    s = requests.Session()
    # ignore any proxy setting because we should have a direct connection
    s.trust_env = False
    return s


def is_alive(host, port, timeout=None):
    timeout = timeout or cfg.CONF.alive_timeout
    path = ASTARA_BASE_PATH + 'firewall/rules'
    try:
        s = _get_proxyless_session()
        r = s.get(_mgt_url(host, port, path), timeout=timeout)
        if r.status_code == 200:
            return True
    except Exception as e:
        LOG.debug('is_alive for %s failed: %s', host, str(e))
    return False


def get_interfaces(host, port):
    path = ASTARA_BASE_PATH + 'system/interfaces'
    s = _get_proxyless_session()
    r = s.get(_mgt_url(host, port, path), timeout=30)
    return r.json().get('interfaces', [])


@retry_on_failure
def update_config(host, port, config_dict):
    path = ASTARA_BASE_PATH + 'system/config'
    headers = {'Content-type': 'application/json'}

    s = _get_proxyless_session()

    r = s.put(
        _mgt_url(host, port, path),
        data=jsonutils.dump_as_bytes(config_dict),
        headers=headers,
        timeout=cfg.CONF.config_timeout)

    if r.status_code == 200:
        return r.json()

    raise Exception('Config update failed: %s' % r.text)


def read_labels(host, port):
    path = ASTARA_BASE_PATH + 'firewall/labels'
    s = _get_proxyless_session()
    r = s.post(_mgt_url(host, port, path), timeout=30)
    return r.json().get('labels', [])
