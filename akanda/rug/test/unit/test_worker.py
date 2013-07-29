import mock
import unittest2 as unittest

from akanda.rug import worker


class TestWorker(unittest.TestCase):

    def setUp(self):
        super(TestWorker, self).setUp()
        self.w = worker.Worker()

    @mock.patch('akanda.rug.state.Automaton')
    def test_new_router(self, automaton):
        self.w.handle_message('1234', {'key': 'value'})
        self.assertIn('1234', self.w.state_machines)
        automaton.assert_called_with(
            router_id='1234',
            delete_callback=self.w._delete_router,
        )

    def test_delete_router(self):
        self.w.state_machines['1234'] = mock.Mock()
        self.w._delete_router('1234')
        self.assertNotIn('1234', self.w.state_machines)
