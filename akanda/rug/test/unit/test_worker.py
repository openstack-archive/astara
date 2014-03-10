import os
import tempfile

import mock

import unittest2 as unittest

from akanda.rug import commands
from akanda.rug import event
from akanda.rug import notifications
from akanda.rug import vm_manager
from akanda.rug import worker


class TestCreatingRouter(unittest.TestCase):

    def setUp(self):
        super(TestCreatingRouter, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

        mock.patch('akanda.rug.worker.nova').start()
        mock.patch('akanda.rug.worker.quantum').start()

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
        super(TestCreatingRouter, self).tearDown()

    def test_in_tenant_managers(self):
        self.assertIn(self.tenant_id, self.w.tenant_managers)
        trm = self.w.tenant_managers[self.tenant_id]
        self.assertEqual(self.tenant_id, trm.tenant_id)

    def test_message_enqueued(self):
        trm = self.w.tenant_managers[self.tenant_id]
        sm = trm.get_state_machines(self.msg, worker.WorkerContext())[0]
        self.assertEqual(1, len(sm._queue))


class TestWildcardMessages(unittest.TestCase):

    def setUp(self):
        super(TestWildcardMessages, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

        mock.patch('akanda.rug.worker.nova').start()
        mock.patch('akanda.rug.worker.quantum').start()

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
        super(TestWildcardMessages, self).tearDown()

    def test_wildcard_to_all(self):
        trms = self.w._get_trms('*')
        ids = sorted(trm.tenant_id for trm in trms)
        self.assertEqual(['1234', '5678'], ids)


class TestShutdown(unittest.TestCase):

    def setUp(self):
        super(TestShutdown, self).setUp()
        mock.patch('akanda.rug.worker.nova').start()
        mock.patch('akanda.rug.worker.quantum').start()
        self.addCleanup(mock.patch.stopall)

    def test_shutdown_on_null_message(self):
        self.w = worker.Worker(0, mock.Mock())
        with mock.patch.object(self.w, '_shutdown') as meth:
            self.w.handle_message(None, None)
            meth.assert_called_once_with()

    def test_stop_threads(self):
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
    def test_stop_threads_notifier(self, producer, exchange, broker):
        notifier = notifications.Publisher('url', 'quantum', 'topic')
        self.w = worker.Worker(0, notifier)
        self.assertTrue(self.w.notifier._t)
        self.w._shutdown()
        self.assertFalse(self.w.notifier._t)


class TestUpdateStateMachine(unittest.TestCase):

    def setUp(self):
        super(TestUpdateStateMachine, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

        mock.patch('akanda.rug.worker.nova').start()
        mock.patch('akanda.rug.worker.quantum').start()

        self.worker_context = worker.WorkerContext()

        self.addCleanup(mock.patch.stopall)

    def test(self):
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
        sm = trm.get_state_machines(msg, self.worker_context)[0]
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
            used_context = w._thread_target()
            meth.assert_called_once_with(used_context)


class TestReportStatus(unittest.TestCase):

    def setUp(self):
        super(TestReportStatus, self).setUp()
        mock.patch('akanda.rug.worker.nova').start()
        mock.patch('akanda.rug.worker.quantum').start()
        self.addCleanup(mock.patch.stopall)

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


class TestDebugRouters(unittest.TestCase):

    def setUp(self):
        super(TestDebugRouters, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

        mock.patch('akanda.rug.worker.nova').start()
        mock.patch('akanda.rug.worker.quantum').start()

        self.w = worker.Worker(0, mock.Mock())

        self.addCleanup(mock.patch.stopall)

    def testNoDebugs(self):
        self.assertEqual(set(), self.w._debug_routers)

    def testWithDebugs(self):
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.ROUTER_DEBUG,
                                     'router_id': 'this-router-id'}}),
        )
        self.assertEqual(set(['this-router-id']), self.w._debug_routers)

    def testManage(self):
        self.w._debug_routers = set(['this-router-id'])
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.ROUTER_MANAGE,
                                     'router_id': 'this-router-id'}}),
        )
        self.assertEqual(set(), self.w._debug_routers)

    def testDebugging(self):
        self.w._debug_routers = set(['5678'])

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
        trm = self.w._get_trms(tenant_id)[0]
        sm = trm.get_state_machines(msg, worker.WorkerContext())[0]
        with mock.patch.object(sm, 'send_message') as meth:
            # The router id is being ignored, so the send_message()
            # method shouldn't ever be invoked.
            meth.side_effect = AssertionError('send_message was called')
            self.w.handle_message(tenant_id, msg)


class TestIgnoreRouters(unittest.TestCase):

    def setUp(self):
        super(TestIgnoreRouters, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

        mock.patch('akanda.rug.worker.nova').start()
        mock.patch('akanda.rug.worker.quantum').start()

        self.addCleanup(mock.patch.stopall)

    def testNoIgnorePath(self):
        w = worker.Worker(0, mock.Mock(), ignore_directory=None)
        ignored = w._get_routers_to_ignore()
        self.assertEqual(set(), ignored)

    def testNoIgnores(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: os.rmdir(tmpdir))
        w = worker.Worker(0, mock.Mock(), ignore_directory=tmpdir)
        ignored = w._get_routers_to_ignore()
        self.assertEqual(set(), ignored)

    def testWithIgnores(self):
        tmpdir = tempfile.mkdtemp()
        fullname = os.path.join(tmpdir, 'this-router-id')
        with open(fullname, 'a'):
            os.utime(fullname, None)
        self.addCleanup(lambda: os.unlink(fullname) and os.rmdir(tmpdir))
        w = worker.Worker(0, mock.Mock(), ignore_directory=tmpdir)
        ignored = w._get_routers_to_ignore()
        self.assertEqual(set(['this-router-id']), ignored)

    def testManage(self):
        w = worker.Worker(0, mock.Mock())
        w._debug_routers = set(['this-router-id'])
        w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.ROUTER_MANAGE,
                                     'router_id': 'this-router-id'}}),
        )
        self.assertEqual(set(), w._debug_routers)

    def testIgnoring(self):
        tmpdir = tempfile.mkdtemp()
        fullname = os.path.join(tmpdir, '5678')
        with open(fullname, 'a'):
            os.utime(fullname, None)
        self.addCleanup(lambda: os.unlink(fullname) and os.rmdir(tmpdir))
        w = worker.Worker(0, mock.Mock(), ignore_directory=tmpdir)

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
        sm = trm.get_state_machines(msg, worker.WorkerContext())[0]
        with mock.patch.object(sm, 'send_message') as meth:
            # The router id is being ignored, so the send_message()
            # method shouldn't ever be invoked.
            meth.side_effect = AssertionError('send_message was called')
            w.handle_message(tenant_id, msg)


class TestDebugTenants(unittest.TestCase):

    def setUp(self):
        super(TestDebugTenants, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

        mock.patch('akanda.rug.worker.nova').start()
        mock.patch('akanda.rug.worker.quantum').start()

        self.w = worker.Worker(0, mock.Mock())

        self.addCleanup(mock.patch.stopall)

    def testNoDebugs(self):
        self.assertEqual(set(), self.w._debug_tenants)

    def testWithDebugs(self):
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.TENANT_DEBUG,
                                     'tenant_id': 'this-tenant-id'}}),
        )
        self.assertEqual(set(['this-tenant-id']), self.w._debug_tenants)

    def testManage(self):
        self.w._debug_tenants = set(['this-tenant-id'])
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.TENANT_MANAGE,
                                     'tenant_id': 'this-tenant-id'}}),
        )
        self.assertEqual(set(), self.w._debug_tenants)

    def testDebugging(self):
        self.w._debug_tenants = set(['1234'])

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
        trm = self.w._get_trms(tenant_id)[0]
        sm = trm.get_state_machines(msg, worker.WorkerContext())[0]
        with mock.patch.object(sm, 'send_message') as meth:
            # The tenant id is being ignored, so the send_message()
            # method shouldn't ever be invoked.
            meth.side_effect = AssertionError('send_message was called')
            self.w.handle_message(tenant_id, msg)
