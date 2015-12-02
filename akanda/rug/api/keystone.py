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
from keystoneclient import session as kssession

from oslo_config import cfg


CONF = cfg.CONF


class KeystoneSession(object):
    def __init__(self):
        self._session = None
        self.region_name = CONF.auth_region
        ksauth.register_conf_options(CONF, 'keystone_authtoken')

    @property
    def session(self):
        if not self._session:
            # Construct a Keystone session for configured auth_plugin
            # and credentials
            auth_plugin = ksauth.load_from_conf_options(
                cfg.CONF, 'keystone_authtoken')
            self._session = kssession.Session(auth=auth_plugin)
        return self._session
