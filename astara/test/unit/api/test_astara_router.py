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


import mock

from astara.api import astara_client
from astara.test.unit import base


class TestRugClient(base.RugTestBase):
    def setUp(self):
        super(TestRugClient, self).setUp()
        self.mock_create_session = mock.patch.object(
            astara_client,
            '_get_proxyless_session'
        ).start()
        self.mock_get = self.mock_create_session.return_value.get
        self.mock_put = self.mock_create_session.return_value.put
        self.mock_post = self.mock_create_session.return_value.post

        self.addCleanup(mock.patch.stopall)

    def test_mgt_url(self):
        self.assertEqual('http://[fe80::2]:5000/',
                         astara_client._mgt_url('fe80::2', 5000, '/'))
        self.assertEqual('http://192.168.1.1:5000/',
                         astara_client._mgt_url('192.168.1.1', 5000, '/'))

    def test_is_alive_success(self):
        self.mock_get.return_value.status_code = 200

        self.assertTrue(astara_client.is_alive('fe80::2', 5000))
        self.mock_get.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/rules',
            timeout=3.0
        )

    def test_is_alive_bad_status(self):
        self.mock_get.return_value.status_code = 500

        self.assertFalse(astara_client.is_alive('fe80::2', 5000))
        self.mock_get.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/rules',
            timeout=3.0
        )

    def test_is_alive_exception(self):
        self.mock_get.side_effect = Exception

        self.assertFalse(astara_client.is_alive('fe80::2', 5000))
        self.mock_get.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/rules',
            timeout=3.0
        )

    def test_get_interfaces(self):
        self.mock_get.return_value.status_code = 200
        self.mock_get.return_value.json.return_value = {
            'interfaces': 'the_interfaces'
        }

        self.assertEqual(astara_client.get_interfaces('fe80::2', 5000),
                         'the_interfaces')
        self.mock_get.assert_called_once_with(
            'http://[fe80::2]:5000/v1/system/interfaces',
            timeout=30
        )

    def test_update_config(self):
        config = {'foo': 'bar'}
        self.mock_put.return_value.status_code = 200
        self.mock_put.return_value.json.return_value = config

        resp = astara_client.update_config('fe80::2', 5000, config)

        self.mock_put.assert_called_once_with(
            'http://[fe80::2]:5000/v1/system/config',
            data='{"foo": "bar"}',
            headers={'Content-type': 'application/json'},
            timeout=90)
        self.assertEqual(resp, config)

    def test_update_config_with_custom_config(self):
        config = {'foo': 'bar'}
        self.mock_put.return_value.status_code = 200
        self.mock_put.return_value.json.return_value = config

        with mock.patch.object(astara_client.cfg, 'CONF') as cfg:
            cfg.config_timeout = 5
            resp = astara_client.update_config('fe80::2', 5000, config)

            self.mock_put.assert_called_once_with(
                'http://[fe80::2]:5000/v1/system/config',
                data='{"foo": "bar"}',
                headers={'Content-type': 'application/json'},
                timeout=5)
            self.assertEqual(resp, config)

    def test_update_config_failure(self):
        self.config(max_retries=5)
        config = {'foo': 'bar'}

        self.mock_put.return_value.status_code = 500
        self.mock_put.return_value.text = 'error_text'

        self.assertRaises(
            astara_client.AstaraAPITooManyAttempts,
            astara_client.update_config, 'fe80::2', 5000, config)

        self.assertEqual(len(self.mock_put.call_args_list), 5)
        self.mock_put.assert_called_with(
            'http://[fe80::2]:5000/v1/system/config',
            data='{"foo": "bar"}',
            headers={'Content-type': 'application/json'},
            timeout=90
        )

    def test_read_labels(self):
        self.mock_post.return_value.status_code = 200
        self.mock_post.return_value.json.return_value = {
            'labels': ['label1', 'label2']
        }
        resp = astara_client.read_labels('fe80::2', 5000)

        self.mock_post.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/labels',
            timeout=30
        )

        self.assertEqual(resp, ['label1', 'label2'])
