import unittest

from cliff import commandmanager

from akanda.rug.api import rug
import mock
import webob


class TestRugAPI(unittest.TestCase):

    def setUp(self):
        ctl = mock.Mock()
        ctl.return_value.command_manager = commandmanager.CommandManager(
            'akanda.rug.cli'
        )
        self.api = rug.RugAPI(ctl)
        self.ctl = ctl.return_value

    def test_browse(self):
        resp = self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/browse/'
        }))
        assert isinstance(resp, webob.exc.HTTPNotImplemented)
        assert not self.ctl.run.called

    def test_ssh(self):
        resp = self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/ssh/ROUTER123/'
        }))
        assert isinstance(resp, webob.exc.HTTPNotImplemented)
        assert not self.ctl.run.called

    def test_poll(self):
        self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/poll/'
        }))
        self.ctl.run.assert_called_with(
            ['--debug', 'poll']
        )

    def test_missing_argument(self):
        # argparse failures (e.g., a missing router ID) raise a SystemExit
        # because cliff's behavior is to print a help message and sys.exit()
        self.ctl.run.side_effect = SystemExit
        resp = self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/router/debug/'
        }))
        assert isinstance(resp, webob.exc.HTTPBadRequest)
        self.ctl.run.assert_called_with(
            ['--debug', 'router', 'debug']
        )

    def test_router_debug(self):
        self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/router/debug/ROUTER123'
        }))
        self.ctl.run.assert_called_with(
            ['--debug', 'router', 'debug', 'ROUTER123']
        )

    def test_router_manage(self):
        self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/router/manage/ROUTER123'
        }))
        self.ctl.run.assert_called_with(
            ['--debug', 'router', 'manage', 'ROUTER123']
        )

    def test_router_update(self):
        self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/router/update/ROUTER123'
        }))
        self.ctl.run.assert_called_with(
            ['--debug', 'router', 'update', 'ROUTER123']
        )

    def test_router_rebuild(self):
        self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/router/rebuild/ROUTER123'
        }))
        self.ctl.run.assert_called_with(
            ['--debug', 'router', 'rebuild', 'ROUTER123']
        )

    def test_tenant_debug(self):
        self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/tenant/debug/TENANT123'
        }))
        self.ctl.run.assert_called_with(
            ['--debug', 'tenant', 'debug', 'TENANT123']
        )

    def test_tenant_manage(self):
        self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/tenant/manage/TENANT123'
        }))
        self.ctl.run.assert_called_with(
            ['--debug', 'tenant', 'manage', 'TENANT123']
        )

    def test_workers_debug(self):
        self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/workers/debug/'
        }))
        self.ctl.run.assert_called_with(
            ['--debug', 'workers', 'debug']
        )

    def test_invalid_router_action(self):
        resp = self.api(webob.Request({
            'REQUEST_METHOD': 'PUT',
            'PATH_INFO': '/router/breakdance/ROUTER123'
        }))
        assert isinstance(resp, webob.exc.HTTPNotFound)
        assert not self.ctl.run.called

    def test_multiple_calls(self):
        for i in range(10):
            self.api(webob.Request({
                'REQUEST_METHOD': 'PUT',
                'PATH_INFO': '/poll/'
            }))

        assert self.ctl.run.call_args_list == [
            mock.call(['--debug', 'poll'])
            for _ in range(10)
        ]

    def test_invalid_request_method(self):
        resp = self.api(webob.Request({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/poll/'
        }))
        assert isinstance(resp, webob.exc.HTTPMethodNotAllowed)
        assert not self.ctl.run.called
