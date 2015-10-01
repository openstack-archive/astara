# Copyright (c) 2015 Akanda, Inc. All Rights Reserved.
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

from keystoneclient import auth as ksauth
from keystoneclient import exceptions as ksexception
from keystoneclient import session as kssession

# NOTE(deva): import auth_token so oslo_config pulls in keystone_authtoken
from keystonemiddleware import auth_token  # noqa

from oslo_config import cfg
from oslo_log import log as logging

from akanda.rug.common.i18n import _, _LW
#from ironic.common import exception
#from ironic.common.i18n import _, _LW
#from ironic.openstack.common import log as logging

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


#CONF.register_opts(keystone_opts, group='keystone')

CONF.import_opt('auth_uri', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')
CONF.import_opt('admin_user', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')
CONF.import_opt('admin_password', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')
CONF.import_opt('admin_tenant_name', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')


class KeystoneSession(object):
    def __init__(self, token=None):
        self._session = None
        self._auth_ref = None
        self._token = token
        self.region_name = CONF.auth_region

    @property
    def session(self):
        if not self._session:
            # Construct a Keystone session for configured auth_plugin
            # and credentials
            auth_plugin = ksauth.load_from_conf_options(
                cfg.CONF, 'keystone_authtoken')
            self._session = kssession.Session(auth=auth_plugin)
        return self._session
