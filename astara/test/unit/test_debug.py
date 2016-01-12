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

from oslo_config import cfg

from astara import debug
from astara.test.unit import base


class TestDebug(base.RugTestBase):
    def tearDown(self):
        # The router-id CLI opt is added at runtime and needs to be removed
        # post-test to avoid polluting other tests' config namespace
        cfg.CONF.reset()
        cfg.CONF.unregister_opts(debug.DEBUG_OPTS)
        super(TestDebug, self).tearDown()

    @mock.patch('astara.drivers.get')
    @mock.patch('astara.worker.WorkerContext')
    @mock.patch('astara.state.Automaton')
    @mock.patch('pdb.set_trace')
    def test_debug_one_router(self, set_trace, automaton, ctx, drivers_get):
        ctx.return_value.neutron.get_router_detail.return_value = mock.Mock(
            tenant_id='123'
        )
        debug.debug_one_router(self.argv + ['--router-id', 'X'])

        mock_router = drivers_get.return_value.return_value._router

        assert set_trace.called
        automaton.assert_called_once_with(
            resource=drivers_get.return_value.return_value,
            tenant_id=mock_router.tenant_id,
            delete_callback=debug.delete_callback,
            bandwidth_callback=debug.bandwidth_callback,
            worker_context=ctx.return_value,
            queue_warning_threshold=100,
            reboot_error_threshold=1,
        )

        class CrudMatch(object):

            def __init__(self, crud):
                self.crud = crud

            def __eq__(self, other):
                return self.crud == other.crud

        automaton.return_value.send_message.assert_called_once_with(
            CrudMatch('update')
        )
        self.assertEqual(automaton.return_value.update.call_count, 1)
