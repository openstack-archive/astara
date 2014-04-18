import mock
import unittest2 as unittest

from akanda.rug import debug


class TestDebug(unittest.TestCase):

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
            'X',
            '123',
            debug.delete_callback,
            debug.bandwidth_callback,
            ctx.return_value,
            100
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
