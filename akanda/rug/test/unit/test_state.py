import mock
import unittest2 as unittest

from akanda.rug import state


class TestAutomaton(unittest.TestCase):

    def setUp(self):
        super(TestAutomaton, self).setUp()
        self.queue = mock.Mock()
        self.sm = state.Automaton(
            router_id='9306bbd8-f3cc-11e2-bd68-080027e60b25',
            delete_callback=mock.Mock(),
            queue=self.queue
        )

    def test_send_message(self):
        message = 'message'
        self.sm.send_message(message)
        self.queue.put.assert_called_once_with(message)

    def test_has_more_work(self):
        self.queue.empty.return_value = False
        self.assertTrue(self.sm.has_more_work())
