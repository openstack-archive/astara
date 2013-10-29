import requests

from akanda.rug.openstack.common import jsonutils

AKANDA_ULA_PREFIX = 'fdca:3ba5:a17a:acda::/64'
AKANDA_MGT_SERVICE_PORT = 5000
AKANDA_BASE_PATH = '/v1/'


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
    path = AKANDA_BASE_PATH + 'firewall/labels'
    try:
        s = _get_proxyless_session()
        r = s.get(_mgt_url(host, port, path), timeout=1.0)
        if r.status_code == 200:
            return True
    except:
        pass
    return False


def get_interfaces(host, port):
    path = AKANDA_BASE_PATH + 'system/interfaces'
    s = _get_proxyless_session()
    r = s.get(_mgt_url(host, port, path))
    return r.json().get('interfaces', [])


def update_config(host, port, config_dict):
    path = AKANDA_BASE_PATH + 'system/config'
    headers = {'Content-type': 'application/json'}

    s = _get_proxyless_session()
    r = s.put(
        _mgt_url(host, port, path),
        data=jsonutils.dumps(config_dict),
        headers=headers)

    if r.status_code != 200:
        raise Exception('Config update failed: %s' % r.text)
    else:
        return r.json()


def read_labels(host, port):
    path = AKANDA_BASE_PATH + 'firewall/labels'
    s = _get_proxyless_session()
    r = s.post(_mgt_url(host, port, path))
    return r.json().get('labels', [])
