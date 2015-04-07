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

from neutronclient.common import exceptions as q_exceptions

from akanda.rug import populate


class TestPrePopulateWorkers(unittest.TestCase):

    @mock.patch('akanda.rug.api.neutron.Neutron')
    def test_retry_loop(self, mocked_neutron_api):
        neutron_client = mock.Mock()
        returned_value = [Exception, []]
        neutron_client.get_routers.side_effect = returned_value
        neutron_client.get_ready_loadbalancers.return_value = {}
        mocked_neutron_api.return_value = neutron_client

        sched = mock.Mock()
        populate._pre_populate_workers(sched)
        self.assertEqual(
            neutron_client.get_routers.call_args_list,
            [
                mock.call(detailed=False)
                for value in xrange(len(returned_value))
            ]
        )
        self.assertEqual(
            neutron_client.get_routers.call_count,
            len(returned_value)
        )

    def _exit_loop_bad_auth(self, mocked_neutron_api, log, exc):
        neutron_client = mock.Mock()
        neutron_client.get_routers.side_effect = exc
        mocked_neutron_api.return_value = neutron_client
        sched = mock.Mock()
        populate._pre_populate_workers(sched)
        log.warning.assert_called_once_with(
            'PrePopulateWorkers thread failed: %s',
            mock.ANY
        )

    @mock.patch('akanda.rug.populate.LOG')
    @mock.patch('akanda.rug.api.neutron.Neutron')
    def test_exit_loop_unauthorized(self, mocked_neutron_api, log):
        exc = q_exceptions.Unauthorized
        self._exit_loop_bad_auth(mocked_neutron_api, log, exc)

    @mock.patch('akanda.rug.populate.LOG')
    @mock.patch('akanda.rug.api.neutron.Neutron')
    def test_exit_loop_forbidden(self, mocked_neutron_api, log):
        exc = q_exceptions.Forbidden
        self._exit_loop_bad_auth(mocked_neutron_api, log, exc)

    @mock.patch('akanda.rug.event.Event')
    @mock.patch('akanda.rug.api.neutron.Neutron')
    def test_scheduler_handle_message(self, mocked_neutron_api, event):

        def message_to_router_args(message):
            tmp = message.copy()
            tmp['id'] = tmp.pop('router_id')
            return tmp

        neutron_client = mock.Mock()
        message1 = {'tenant_id': '1', 'router_id': '2',
                    'body': {}, 'crud': 'poll'}
        message2 = {'tenant_id': '3', 'router_id': '4',
                    'body': {}, 'crud': 'poll'}

        message3 = {'tenant_id': '1', 'router_id': '6',
                    'body': {}, 'crud': 'poll'}
        message4 = {'tenant_id': '3', 'router_id': '8',
                    'body': {}, 'crud': 'poll'}

        return_value = [
            mock.Mock(**message_to_router_args(message1)),
            mock.Mock(**message_to_router_args(message2))
        ]
        return_value_lb = [
            mock.Mock(**message_to_router_args(message3)),
            mock.Mock(**message_to_router_args(message4))
        ]

        neutron_client.get_routers.return_value = return_value
        neutron_client.get_ready_loadbalancers.return_value = return_value_lb

        sched = mock.Mock()
        mocked_neutron_api.return_value = neutron_client
        populate._pre_populate_workers(sched)

        self.assertEqual(sched.handle_message.call_count, 4)

        self.assertEqual(event.call_count, 4)

    @mock.patch('threading.Thread')
    def test_pre_populate_workers(self, thread):
        sched = mock.Mock()
        t = populate.pre_populate_workers(sched)
        thread.assert_called_once_with(
            target=populate._pre_populate_workers,
            args=(sched,),
            name='PrePopulateWorkers'
        )
        self.assertEqual(
            t.mock_calls,
            [mock.call.setDaemon(True), mock.call.start()]
        )
