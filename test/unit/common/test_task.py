import mock
import unittest2 as unittest

from akanda.rug.common import task


class TestTask(unittest.TestCase):
    def test_init(self):
        t = task.Task('the_method', 'data')
        self.assertEqual(t.method, 'the_method')
        self.assertEqual(t.data, 'data')
        self.assertEqual(t.current, 0)
        self.assertEqual(t.max_attempts, 3)

    def test_call(self):
        method = mock.Mock()

        t = task.Task(method, 'data', 3)
        t()

        self.assertEqual(t.current, 1)
        method.assert_called_once_with('data')

    def test_should_retry(self):
        method = mock.Mock()

        t = task.Task(method, 'data', 1)
        self.assertTrue(t.should_retry())
        t()
        self.assertFalse(t.should_retry())
        method.assert_called_once_with('data')

    def test_repr(self):
        method = mock.Mock()
        method.__name__ = 'method'

        t = task.Task(method, 'data', 1)

        self.assertEqual(
            repr(t),
            '<Task method: method data: data attempt: 0/1 >')


class TestTaskManager(unittest.TestCase):
    def test_init(self):
        tm = task.TaskManager(10)

    def test_put(self):
        tm = task.TaskManager(10)
        tm.put('method', 'data')

        self.assertEqual(tm.task_queue.qsize(), 1)
        qt = tm.task_queue.get()

        self.assertEqual(qt.method, 'method')
        self.assertEqual(qt.data, 'data')
        self.assertEqual(qt.max_attempts, 3)

    def test_start(self):
        with mock.patch('eventlet.spawn') as spawn:
            tm = task.TaskManager(10)
            tm.start()

            spawn.assert_has_calls([
                mock.call.spawn(tm._serialized_task_runner),
                mock.call.spawn(tm._requeue_failed)])

    def test_task_runner(self):
        tm = task.TaskManager(10)

        with mock.patch.object(tm, 'task_queue') as q:
            with mock.patch.object(task, 'LOG') as log:
                # We need to mock the Log object and not just Log.info.
                # Inside _serialized_task_runner a call to the get method on
                # task_queue return a task object. Subsequent Log.debug calls
                # that print the task object are considered by mock as calls on
                # the task_queue mocked object and listed as
                # mock.call.get().__str__() in the chain of calls of the
                # assert_has_calls method.
                # Mocking the LOG.debug object the task object is not
                # actually printed leaving the chain of calls looking like how
                # we expect it to be
                log.info.side_effect = [None, IOError]
                try:
                    tm._serialized_task_runner()
                except IOError:
                    pass
            q.assert_has_calls([mock.call.get(), mock.call.get()()])

    def test_task_runner_exception_during_task(self):
        tm = task.TaskManager(10)

        mock_task = mock.Mock()
        mock_task.should_retry.return_value = True
        mock_task.side_effect = Exception

        with mock.patch.object(tm, 'task_queue') as q:
            q.get.return_value = mock_task
            with mock.patch.object(task.LOG, 'info') as info:
                info.side_effect = [None, IOError]
                try:
                    tm._serialized_task_runner()
                except IOError:
                    pass
            q.assert_has_calls([mock.call.get(), mock.call.get()()])
            self.assertEqual(tm.delay_queue.qsize(), 1)

    def test_task_runner_exception_during_task_out_of_retries(self):
        tm = task.TaskManager(10)

        mock_task = mock.Mock()
        mock_task.should_retry.return_value = False
        mock_task.side_effect = Exception

        with mock.patch.object(tm, 'task_queue') as q:
            q.get.return_value = mock_task
            with mock.patch.object(task.LOG, 'info') as info:
                info.side_effect = [None, IOError]
                with mock.patch.object(task.LOG, 'error') as error:
                    try:
                        tm._serialized_task_runner()
                    except IOError:
                        pass
                q.assert_has_calls([mock.call.get(), mock.call.get()()])
                self.assertEqual(tm.delay_queue.qsize(), 0)
                self.assertEqual(len(error.mock_calls), 2)

    def test_requeue_failed(self):
        tm = task.TaskManager(10)
        with mock.patch('eventlet.sleep') as sleep:
            sleep.side_effect = [None, IOError]
            tm.delay_queue.put(mock.Mock())
            try:
                tm._requeue_failed()
            except IOError:
                pass
            self.assertEqual(tm.task_queue.qsize(), 1)
            self.assertEqual(tm.delay_queue.qsize(), 0)
