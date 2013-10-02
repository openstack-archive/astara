import json

import mock
import unittest2 as unittest

from akanda.rug.api import akanda_client


class TestAkandaClient(unittest.TestCase):
    def setUp(self):
        self.mock_httplib_p = mock.patch('httplib2.Http')
        self.mock_httplib = self.mock_httplib_p.start()
        self.mock_request = self.mock_httplib.return_value.request

    def tearDown(self):
        self.mock_httplib_p.stop()

    def test_mgt_url(self):
        self.assertEqual('http://[fe80::2]:5000/',
                         akanda_client._mgt_url('fe80::2', 5000, '/'))
        self.assertEqual('http://192.168.1.1:5000/',
                         akanda_client._mgt_url('192.168.1.1', 5000, '/'))

    def test_is_alive_success(self):
        response = mock.Mock(status=200)
        self.mock_request.return_value = (response, '')

        self.assertTrue(akanda_client.is_alive('fe80::2', 5000))
        self.mock_request.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/labels',
        )

    def test_is_alive_bad_status(self):
        response = mock.Mock(status=500)
        self.mock_request.return_value = (response, '')

        self.assertFalse(akanda_client.is_alive('fe80::2', 5000))
        self.mock_request.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/labels'
        )

    def test_is_alive_exception(self):
        self.mock_request.side_effect = Exception

        self.assertFalse(akanda_client.is_alive('fe80::2', 5000))
        self.mock_request.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/labels'
        )

    def test_get_interfaces(self):
        response = mock.Mock(status=200)
        self.mock_request.return_value = (
            response,
            json.dumps({'interfaces': 'the_interfaces'})
        )

        self.assertEqual(akanda_client.get_interfaces('fe80::2', 5000),
                         'the_interfaces')
        self.mock_request.assert_called_once_with(
            'http://[fe80::2]:5000/v1/system/interfaces'
        )

    def test_update_config(self):
        config = {'foo': 'bar'}
        mock_response = mock.Mock(status=200)
        self.mock_request.return_value = (mock_response, json.dumps(config))

        resp = akanda_client.update_config('fe80::2', 5000, config)

        self.mock_request.assert_called_once_with(
            'http://[fe80::2]:5000/v1/system/config',
            method='PUT',
            body='{"foo": "bar"}',
            headers={'Content-type': 'application/json'})
        self.assertEqual(resp, config)

    def test_update_config_failure(self):
        config = {'foo': 'bar'}

        mock_response = mock.Mock(status=500)
        self.mock_request.return_value = (mock_response, 'error_text')

        with self.assertRaises(Exception):
            akanda_client.update_config('fe80::2', 5000, config)

        self.mock_request.assert_called_once_with(
            'http://[fe80::2]:5000/v1/system/config',
            method='PUT',
            body='{"foo": "bar"}',
            headers={'Content-type': 'application/json'}
        )

    def test_read_labels(self):
        mock_response = mock.Mock(status=200)
        self.mock_request.return_value = (
            mock_response,
            json.dumps({'labels': ['label1', 'label2']})
        )

        resp = akanda_client.read_labels('fe80::2', 5000)

        self.mock_request.assert_called_once_with(
            'http://[fe80::2]:5000/v1/firewall/labels',
            method='POST'
        )

        self.assertEqual(resp, ['label1', 'label2'])
