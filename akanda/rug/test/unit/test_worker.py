import mock

import unittest2 as unittest

from akanda.rug import commands
from akanda.rug import event
from akanda.rug import notifications
from akanda.rug import vm_manager
from akanda.rug import worker


class TestWorkerCreatingRouter(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def setUp(self, quantum):
        super(TestWorkerCreatingRouter, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'
        self.addCleanup(mock.patch.stopall)

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
        self.assertEqual(1, len(sm._queue))

    def test_being_updated_set(self):
        self.assertIn(self.router_id, self.w.being_updated)


class TestWorkerWildcardMessages(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def setUp(self, quantum):
        super(TestWorkerWildcardMessages, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'
        self.addCleanup(mock.patch.stopall)

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
    def setUp(self, quantum):
        super(TestWorkerUpdateStateMachine, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'
        self.addCleanup(mock.patch.stopall)

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

    def test_report_status_dispatched(self):
        self.w = worker.Worker(0, mock.Mock())
        with mock.patch.object(self.w, 'report_status') as meth:
            self.w.handle_message(
                'debug',
                event.Event('*', '', event.COMMAND,
                            {'payload': {'command': commands.WORKERS_DEBUG}})
            )
            meth.assert_called_once_with()

    def test_handle_message_report_status(self):
        self.w = worker.Worker(0, mock.Mock())
        self.w.handle_message(
            'debug',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.WORKERS_DEBUG}})
        )


class TestWorkerIgnoreRouters(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def setUp(self, quantum):
        super(TestWorkerIgnoreRouters, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'
        self.addCleanup(mock.patch.stopall)

    def testNoIgnores(self):
        w = worker.Worker(0, mock.Mock())
        self.assertEqual(set(), w._ignore_routers)

    def testWithIgnores(self):
        w = worker.Worker(0, mock.Mock())
        w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.ROUTER_DEBUG,
                                     'router_id': 'this-router-id'}}),
        )
        self.assertEqual(set(['this-router-id']), w._ignore_routers)

    def testManage(self):
        w = worker.Worker(0, mock.Mock())
        w._ignore_routers = set(['this-router-id'])
        w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.ROUTER_MANAGE,
                                     'router_id': 'this-router-id'}}),
        )
        self.assertEqual(set(), w._ignore_routers)

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def testIgnoring(self, quantum):
        w = worker.Worker(0, mock.Mock())
        w._ignore_routers = set(['5678'])

        tenant_id = '1234'
        router_id = '5678'
        msg = event.Event(
            tenant_id=tenant_id,
            router_id=router_id,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        # Create the router manager and state machine so we can
        # replace the send_message() method with a mock.
        trm = w._get_trms(tenant_id)[0]
        sm = trm.get_state_machines(msg)[0]
        with mock.patch.object(sm, 'send_message') as meth:
            # The router id is being ignored, so the send_message()
            # method shouldn't ever be invoked.
            meth.side_effect = AssertionError('send_message was called')
            w.handle_message(tenant_id, msg)


class TestWorkerIgnoreTenants(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def setUp(self, quantum):
        super(TestWorkerIgnoreTenants, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'
        self.addCleanup(mock.patch.stopall)

    def testNoIgnores(self):
        w = worker.Worker(0, mock.Mock())
        self.assertEqual(set(), w._ignore_tenants)

    def testWithIgnores(self):
        w = worker.Worker(0, mock.Mock())
        w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.TENANT_DEBUG,
                                     'tenant_id': 'this-tenant-id'}}),
        )
        self.assertEqual(set(['this-tenant-id']), w._ignore_tenants)

    def testManage(self):
        w = worker.Worker(0, mock.Mock())
        w._ignore_tenants = set(['this-tenant-id'])
        w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.TENANT_MANAGE,
                                     'tenant_id': 'this-tenant-id'}}),
        )
        self.assertEqual(set(), w._ignore_tenants)

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def testIgnoring(self, quantum):
        w = worker.Worker(0, mock.Mock())
        w._ignore_tenants = set(['1234'])

        tenant_id = '1234'
        router_id = '5678'
        msg = event.Event(
            tenant_id=tenant_id,
            router_id=router_id,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        # Create the router manager and state machine so we can
        # replace the send_message() method with a mock.
        trm = w._get_trms(tenant_id)[0]
        sm = trm.get_state_machines(msg)[0]
        with mock.patch.object(sm, 'send_message') as meth:
            # The tenant id is being ignored, so the send_message()
            # method shouldn't ever be invoked.
            meth.side_effect = AssertionError('send_message was called')
            w.handle_message(tenant_id, msg)
