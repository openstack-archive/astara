# Copyright 2015 Akanda, Inc.
# All Rights Reserved.
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

import mock

from astara.common import config
from astara.test.unit import base


class TestConfig(base.RugTestBase):
    def _test_get_best_config_path(self, original, expected, files_exist=()):
        def mock_isfile_f(f):
            return f in files_exist

        with mock.patch('os.path.isfile', side_effect=mock_isfile_f):
            self.assertEqual(
                expected,
                config.get_best_config_path(original)
            )

    def test_get_best_config_path_preferred(self):
        self._test_get_best_config_path(
            config.PREFERRED_CONFIG_FILEPATH,
            config.PREFERRED_CONFIG_FILEPATH
        )

    def test_get_best_config_path_legacy(self):
        self._test_get_best_config_path(
            config.PREFERRED_CONFIG_FILEPATH,
            '/etc/akanda/rug.ini',
            ('/etc/akanda/rug.ini',)
        )
