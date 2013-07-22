import mock
import unittest2 as unittest

from akanda.rug import scheduler


class TestScheduler(unittest.TestCase):

    def test_invalid_num_workers(self):
        try:
            scheduler.Scheduler(0, lambda x: x)
        except ValueError:
            pass
        else:
            self.fail('Should have raised ValueError')

    @mock.patch('multiprocessing.Process')
    def test_creating_workers(self, process):
        s = scheduler.Scheduler(2, lambda x: x)
        self.assertEqual(2, len(s.workers))

    @mock.patch('multiprocessing.Process')
    @mock.patch('multiprocessing.JoinableQueue')
    def test_stop(self, process, queue):
        s = scheduler.Scheduler(2, lambda x: x)
        s.stop()
        for w in s.workers:
            w['queue'].put.assert_called_once(None)
            w['queue'].close.assert_called_once()
            w['worker'].join.assert_called_once()
