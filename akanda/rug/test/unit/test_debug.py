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

from oslo.config import cfg

from akanda.rug import debug


class TestDebug(unittest.TestCase):
    def tearDown(self):
        # The router-id CLI opt is added at runtime and needs to be removed
        # post-test to avoid polluting other tests' config namespace
        cfg.CONF.reset()
        cfg.CONF.unregister_opts(debug.DEBUG_OPTS)
        super(TestDebug, self).tearDown()

    @mock.patch('akanda.rug.worker.WorkerContext')
    @mock.patch('akanda.rug.state.Automaton')
    @mock.patch('pdb.set_trace')
    def test_debug_one_router(self, set_trace, automaton, ctx):
        ctx.return_value.neutron.get_router_detail.return_value = mock.Mock(
            tenant_id='123'
        )
        debug.debug_one_router(['--router-id', 'X'])

        ctx.return_value.neutron.get_router_detail.assert_called_once_with('X')
        assert set_trace.called
        automaton.assert_called_once_with(
            router_id='X',
            tenant_id='123',
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
        automaton.return_value.update.assert_called
