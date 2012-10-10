import mock
import unittest2 as unittest

from akanda.rug.api import akanda_client


class TestAkandaClient(unittest.TestCase):
    def test_mgt_url(self):
        self.assertEqual('http://[fe80::2]:5000/',
                         akanda_client._mgt_url('fe80::2', 5000, '/'))
        self.assertEqual('http://192.168.1.1:5000/',
                         akanda_client._mgt_url('192.168.1.1', 5000, '/'))

    def test_is_alive_success(self):
        with mock.patch('requests.get') as request_get:
            response = mock.Mock()
            response.status_code = 200
            request_get.return_value = response

            self.assertTrue(akanda_client.is_alive('fe80::2', 5000))
            request_get.assert_called_once_with(
                'http://[fe80::2]:5000/v1/firewall/labels',
                timeout=1.0)

    def test_is_alive_bad_status(self):
        with mock.patch('requests.get') as request_get:
            response = mock.Mock()
            response.status_code = 500
            request_get.return_value = response

            self.assertFalse(akanda_client.is_alive('fe80::2', 5000))
            request_get.assert_called_once_with(
                'http://[fe80::2]:5000/v1/firewall/labels',
                timeout=1.0)

    def test_is_alive_exception(self):
        with mock.patch('requests.get') as request_get:
            request_get.side_effect = Exception

            self.assertFalse(akanda_client.is_alive('fe80::2', 5000))
            request_get.assert_called_once_with(
                'http://[fe80::2]:5000/v1/firewall/labels',
                timeout=1.0)

    def test_get_interfaces(self):
        with mock.patch('requests.get') as request_get:
            response = mock.Mock()
            response.status_code = 200
            response.json = {'interfaces': 'the_interfaces'}
            request_get.return_value = response

            self.assertEqual(akanda_client.get_interfaces('fe80::2', 5000),
                             'the_interfaces')
            request_get.assert_called_once_with(
                'http://[fe80::2]:5000/v1/system/interfaces')

    def test_update_config(self):
        config = {'foo': 'bar'}

        with mock.patch('requests.put') as request_put:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_response.json = config
            request_put.return_value = mock_response

            resp = akanda_client.update_config('fe80::2', 5000, config)

            request_put.assert_called_once_with(
                'http://[fe80::2]:5000/v1/system/config',
                data='{"foo": "bar"}',
                headers={'Content-type': 'application/json'})
            self.assertEqual(resp, config)

    def test_update_config_failure(self):
        config = {'foo': 'bar'}

        with mock.patch('requests.put') as request_put:
            mock_response = mock.Mock()
            mock_response.status_code = 500
            mock_response.text = 'error text'
            request_put.return_value = mock_response

            with self.assertRaises(Exception):
                akanda_client.update_config('fe80::2', 5000, config)

            request_put.assert_called_once_with(
                'http://[fe80::2]:5000/v1/system/config',
                data='{"foo": "bar"}',
                headers={'Content-type': 'application/json'})

    def test_read_labels(self):
        with mock.patch('requests.post') as request_post:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_response.json = {'labels': ['label1', 'label2']}
            request_post.return_value = mock_response

            resp = akanda_client.read_labels('fe80::2', 5000)

            request_post.assert_called_once_with(
                'http://[fe80::2]:5000/v1/firewall/labels')

            self.assertEqual(resp, ['label1', 'label2'])
