import mock
import unittest2 as unittest

from akanda.rug import main


@mock.patch('akanda.rug.main.cfg')
@mock.patch('akanda.rug.main.quantum_api')
@mock.patch('akanda.rug.main.multiprocessing')
@mock.patch('akanda.rug.main.notifications')
@mock.patch('akanda.rug.main.scheduler')
@mock.patch('akanda.rug.main.populate')
@mock.patch('akanda.rug.main.health')
@mock.patch('akanda.rug.main.shuffle_notifications')
class TestMainPippo(unittest.TestCase):

    def test_shuffle_notifications(self, shuffle_notifications,
                                   health, populate, scheduler, notifications,
                                   multiprocessing, quantum_api, cfg):
        queue = mock.Mock()
        queue.get.side_effect = [
            ('9306bbd8-f3cc-11e2-bd68-080027e60b25', 'message'),
            KeyboardInterrupt,
        ]
        sched = scheduler.Scheduler.return_value
        main.shuffle_notifications(queue, sched)
        sched.handle_message.assert_called_once('message')
        sched.stop.assert_called_once()

    def test_ensure_local_service_port(self, shuffle_notifications, health,
                                       populate, scheduler, notifications,
                                       multiprocessing, quantum_api, cfg):
        main.main()
        quantum = quantum_api.Quantum.return_value
        quantum.ensure_local_service_port.assert_called_once_with()
