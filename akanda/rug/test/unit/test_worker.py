import mock

import unittest2 as unittest

from akanda.rug import event
from akanda.rug import notifications
from akanda.rug import worker


class TestWorkerCreatingRouter(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def setUp(self, quantum):
        super(TestWorkerCreatingRouter, self).setUp()
        self.w = worker.Worker(0, mock.Mock())
        self.tenant_id = '1234'
        self.router_id = '5678'
        self.msg = event.Event(
            tenant_id=self.tenant_id,
            router_id=self.router_id,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.w.handle_message(self.tenant_id, self.msg)

    def tearDown(self):
        self.w._shutdown()
        super(TestWorkerCreatingRouter, self).tearDown()

    def test_in_tenant_managers(self):
        self.assertIn(self.tenant_id, self.w.tenant_managers)
        trm = self.w.tenant_managers[self.tenant_id]
        self.assertEqual(self.tenant_id, trm.tenant_id)

    def test_message_enqueued(self):
        trm = self.w.tenant_managers[self.tenant_id]
        sm = trm.get_state_machines(self.msg)[0]
        self.assertEqual(1, sm._queue.qsize())

    def test_being_updated_set(self):
        self.assertIn(self.router_id, self.w.being_updated)


class TestWorkerWildcardMessages(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def setUp(self, quantum):
        super(TestWorkerWildcardMessages, self).setUp()
        self.w = worker.Worker(0, mock.Mock())
        # Create some tenants
        for msg in [
                event.Event(
                    tenant_id='1234',
                    router_id='ABCD',
                    crud=event.CREATE,
                    body={'key': 'value'},
                ),
                event.Event(
                    tenant_id='5678',
                    router_id='EFGH',
                    crud=event.CREATE,
                    body={'key': 'value'},
                )]:
            self.w.handle_message(msg.tenant_id, msg)

    def tearDown(self):
        self.w._shutdown()
        super(TestWorkerWildcardMessages, self).tearDown()

    def test_wildcard_to_all(self):
        trms = self.w._get_trms('*')
        ids = sorted(trm.tenant_id for trm in trms)
        self.assertEqual(['1234', '5678'], ids)


class TestWorkerShutdown(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def test_shutdown_on_null_message(self, quantum):
        self.w = worker.Worker(0, mock.Mock())
        with mock.patch.object(self.w, '_shutdown') as meth:
            self.w.handle_message(None, None)
            meth.assert_called_once_with()

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def test_stop_threads(self, quantum):
        self.w = worker.Worker(1, mock.Mock())
        original_queue = self.w.work_queue
        self.assertTrue(self.w._keep_going)
        self.w._shutdown()
        self.assertFalse(self.w._keep_going)
        new_queue = self.w.work_queue
        self.assertIsNot(original_queue, new_queue)

    @mock.patch('kombu.connection.BrokerConnection')
    @mock.patch('kombu.entity.Exchange')
    @mock.patch('kombu.Producer')
    @mock.patch('akanda.rug.api.quantum.Quantum')
    def test_stop_threads_notifier(self, quantum, producer, exchange, broker):
        notifier = notifications.Publisher('url', 'quantum', 'topic')
        self.w = worker.Worker(0, notifier)
        self.assertTrue(self.w.notifier._t)
        self.w._shutdown()
        self.assertFalse(self.w.notifier._t)


class TestWorkerUpdateStateMachine(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def test(self, quantum):
        w = worker.Worker(0, mock.Mock())
        tenant_id = '1234'
        router_id = '5678'
        msg = event.Event(
            tenant_id=tenant_id,
            router_id=router_id,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        # Create the router manager and state machine so we can
        # replace the update() method with a mock.
        trm = w._get_trms(tenant_id)[0]
        sm = trm.get_state_machines(msg)[0]
        with mock.patch.object(sm, 'update') as meth:
            w.handle_message(tenant_id, msg)
            # Add a null message so the worker loop will exit. We have
            # to do this directly, because if we do it through
            # handle_message() that triggers shutdown logic that keeps
            # the loop from working properly.
            w.work_queue.put(None)
            # We aren't using threads (and we trust that threads do
            # work) so we just invoke the thread target ourselves to
            # pretend.
            w._thread_target()
            meth.assert_called_once_with()


class TestWorkerReportStatus(unittest.TestCase):

    def test_handle_message_report_status(self):
        self.w = worker.Worker(0, mock.Mock())
        with mock.patch.object(self.w, 'report_status') as meth:
            self.w.handle_message(
                'debug',
                event.Event('debug', '', event.POLL, {'verbose': 1})
            )
            meth.assert_called_once_with()
