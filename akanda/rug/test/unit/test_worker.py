import mock

import unittest2 as unittest

from akanda.rug import event
from akanda.rug import worker


class TestWorkerCreatingRouter(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def setUp(self, quantum):
        super(TestWorkerCreatingRouter, self).setUp()
        self.w = worker.Worker(0)
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
        sm = trm.get_state_machine(self.msg)
        self.assertEqual(1, sm.queue.qsize())

    def test_being_updated_set(self):
        self.assertIn(self.router_id, self.w.being_updated)


class TestWorkerShutdown(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def test_shutdown_on_null_message(self, quantum):
        self.w = worker.Worker(0)
        with mock.patch.object(self.w, '_shutdown') as meth:
            self.w.handle_message(None, None)
            meth.assert_called_once_with()

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def test_stop_threads(self, quantum):
        self.w = worker.Worker(1)
        original_queue = self.w.work_queue
        self.assertTrue(self.w._keep_going)
        self.w._shutdown()
        self.assertFalse(self.w._keep_going)
        new_queue = self.w.work_queue
        self.assertIsNot(original_queue, new_queue)


class TestWorkerUpdateStateMachine(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def test(self, quantum):
        w = worker.Worker(0)
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
        trm = w._get_trm_for_tenant(tenant_id)
        sm = trm.get_state_machine(msg)
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
