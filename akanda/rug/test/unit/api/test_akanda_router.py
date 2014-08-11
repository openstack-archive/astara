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
import unittest2 as unittest

from akanda.rug.api import akanda_client


class TestAkandaClient(unittest.TestCase):
    def setUp(self):
        self.mock_create_session = mock.patch.object(
            akanda_client,
            '_get_proxyless_session'
        ).start()
        self.mock_get = self.mock_create_session.return_value.get
        self.mock_put = self.mock_create_session.return_value.put
        self.mock_post = self.mock_create_session.return_value.post

        self.addCleanup(mock.patch.stopall)

    def test_mgt_url(self):
        self.assertEqual('http://[fe80::2]:5000/',
                         akanda_client._mgt_url('fe80::2', 5000, '/'))
        self.assertEqual('http://192.168.1.1:5000/',
                         akanda_client._mgt_url('192.168.1.1', 5000, '/'))

    def test_is_alive_success(self):
        self.mock_get.return_value.status_code = 200

        self.assertTrue(akanda_client.is_alive('fe80::2', 5000))
        self.mock_get.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/rules',
            timeout=3.0
        )

    def test_is_alive_bad_status(self):
        self.mock_get.return_value.status_code = 500

        self.assertFalse(akanda_client.is_alive('fe80::2', 5000))
        self.mock_get.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/rules',
            timeout=3.0
        )

    def test_is_alive_exception(self):
        self.mock_get.side_effect = Exception

        self.assertFalse(akanda_client.is_alive('fe80::2', 5000))
        self.mock_get.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/rules',
            timeout=3.0
        )

    def test_get_interfaces(self):
        self.mock_get.return_value.status_code = 200
        self.mock_get.return_value.json.return_value = {
            'interfaces': 'the_interfaces'
        }

        self.assertEqual(akanda_client.get_interfaces('fe80::2', 5000),
                         'the_interfaces')
        self.mock_get.assert_called_once_with(
            'http://[fe80::2]:5000/v1/system/interfaces',
            timeout=30
        )

    def test_update_config(self):
        config = {'foo': 'bar'}
        self.mock_put.return_value.status_code = 200
        self.mock_put.return_value.json.return_value = config

        resp = akanda_client.update_config('fe80::2', 5000, config)

        self.mock_put.assert_called_once_with(
            'http://[fe80::2]:5000/v1/system/config',
            data='{"foo": "bar"}',
            headers={'Content-type': 'application/json'},
            timeout=90)
        self.assertEqual(resp, config)

    def test_update_config_failure(self):
        config = {'foo': 'bar'}

        self.mock_put.return_value.status_code = 500
        self.mock_put.return_value.text = 'error_text'

        with self.assertRaises(Exception):
            akanda_client.update_config('fe80::2', 5000, config)

        self.mock_put.assert_called_once_with(
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
        resp = akanda_client.read_labels('fe80::2', 5000)

        self.mock_post.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/labels',
            timeout=30
        )

        self.assertEqual(resp, ['label1', 'label2'])
