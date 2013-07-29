import mock
import unittest2 as unittest

from akanda.rug import main


class TestMain(unittest.TestCase):

    def test_shuffle_notifications(self):
        queue = mock.Mock()
        queue.get.side_effect = [
            ('9306bbd8-f3cc-11e2-bd68-080027e60b25', 'message'),
            KeyboardInterrupt,
        ]
        sched = mock.Mock()
        main.shuffle_notifications(queue, sched)
        sched.handle_message.assert_called_once('message')
        sched.stop.assert_called_once()
