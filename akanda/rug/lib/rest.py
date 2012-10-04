import netaddr
import requests

from akanda.rug.openstack.common import jsonutils

AKANDA_ULA_PREFIX = 'fdca:3ba5:a17a:acda::/64'
AKANDA_MGT_SERVICE_PORT = 5000
AKANDA_BASE_PATH = '/v1/'


def _mgt_url(host, port, path):
    if ':' in host:
        host = '[%s]' % host
    return 'http://%s:%s%s' % (host, port, path)

def is_alive(host, port):
    path = AKANDA_BASE_PATH + 'system/interfaces'
    try:
        response = requests.get(_mgt_url(host, port, path), timeout=1.0)
        if response.status_code == requests.codes.ok:
            return True
    except:
        pass
    return False

def get_interfaces(host, port):
    path = AKANDA_BASE_PATH + 'system/interfaces'
    response = requests.get(_mgt_url(host, port, path))
    return response.json

def update_config(host, port, config_dict):
    path = AKANDA_BASE_PATH + 'system/config'
    headers = {'Content-type': 'application/json'}
    response = requests.put(_mgt_url(host, port, path),
                            data=jsonutils.dumps(config_dict),
                            headers=headers)

    if response.status_code != request.code.ok:
        raise Exception('Config update failed: %s' % response.text)
