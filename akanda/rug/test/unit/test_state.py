import mock
import unittest2 as unittest

from akanda.rug import state


class TestAutomaton(unittest.TestCase):

    def setUp(self):
        super(TestAutomaton, self).setUp()
        self.sm = state.Automaton(
            router_id='9306bbd8-f3cc-11e2-bd68-080027e60b25',
            delete_callback=mock.Mock(),
        )

    def test_send_message(self):
        message = 'message'
        with mock.patch.object(self.sm._queue, 'put') as meth:
            self.sm.send_message(message)
            meth.assert_called_once_with(message)

    def test_has_more_work(self):
        with mock.patch.object(self.sm._queue, 'empty') as meth:
            meth.return_value = False
            self.assertTrue(self.sm.has_more_work())

    def test_update_no_work(self):
        with mock.patch.object(self.sm._queue, 'empty') as meth:
            self.sm.update()
            meth.assert_called_with()
