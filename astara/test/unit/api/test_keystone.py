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

import mock
from astara.api import keystone

from astara.test.unit import base

from oslo_config import cfg


class KeystoneTest(base.RugTestBase):
    def setUp(self):
        super(KeystoneTest, self).setUp()
        self.config(auth_region='foo_regin')

    @mock.patch('keystoneclient.session.Session')
    @mock.patch('keystoneclient.auth.load_from_conf_options')
    def test_session(self, mock_load_auth, mock_session):
        fake_auth = mock.Mock()
        mock_load_auth.return_value = fake_auth
        fake_session = mock.Mock()
        mock_session.return_value = fake_session
        ks_session = keystone.KeystoneSession().session
        mock_load_auth.assert_called_with(cfg.CONF, 'keystone_authtoken')
        mock_session.assert_called_with(auth=fake_auth)
        self.assertEqual(ks_session, fake_session)
