# Copyright 2014 DreamHost, LLC
#
# Author: DreamHost, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


import os
import tempfile
import threading

import mock

import unittest2 as unittest

from akanda.rug import commands
from akanda.rug import event
from akanda.rug import notifications
from akanda.rug import vm_manager
from akanda.rug import worker

from akanda.rug.api import neutron


class WorkerTestBase(unittest.TestCase):
    def setUp(self):
        super(WorkerTestBase, self).setUp()
        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

        mock.patch('akanda.rug.worker.nova').start()
        fake_neutron_obj = mock.patch.object(
            neutron, 'Neutron', autospec=True).start()
        fake_neutron_obj.get_ports_for_instance.return_value = (
            'mgt_port', ['ext_port', 'int_port'])

        mock.patch.object(neutron, 'Neutron',
                          return_value=fake_neutron_obj).start()
        self.w = worker.Worker(0, mock.Mock())
        self.addCleanup(mock.patch.stopall)


class TestCreatingRouter(WorkerTestBase):
    def setUp(self):
        super(TestCreatingRouter, self).setUp()

        self.w = worker.Worker(0, mock.Mock())
        self.tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        self.router_id = 'ac194fc5-f317-412e-8611-fb290629f624'
        self.hostname = 'akanda'
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


class TestWildcardMessages(WorkerTestBase):

    def setUp(self):
        super(TestWildcardMessages, self).setUp()

        self.w = worker.Worker(0, mock.Mock())
        # Create some tenants
        for msg in [
                event.Event(
                    tenant_id='98dd9c41-d3ac-4fd6-8927-567afa0b8fc3',
                    router_id='ABCD',
                    crud=event.CREATE,
                    body={'key': 'value'},
                ),
                event.Event(
                    tenant_id='ac194fc5-f317-412e-8611-fb290629f624',
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
        self.assertEqual(['98dd9c41-d3ac-4fd6-8927-567afa0b8fc3',
                          'ac194fc5-f317-412e-8611-fb290629f624'],
                         ids)

    def test_wildcard_to_error(self):
        trms = self.w._get_trms('error')
        ids = sorted(trm.tenant_id for trm in trms)
        self.assertEqual(['98dd9c41-d3ac-4fd6-8927-567afa0b8fc3',
                          'ac194fc5-f317-412e-8611-fb290629f624'],
                         ids)


class TestShutdown(WorkerTestBase):
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
        notifier = notifications.Publisher('url', 'neutron', 'topic')
        self.w = worker.Worker(0, notifier)
        self.assertTrue(self.w.notifier._t)
        self.w._shutdown()
        self.assertFalse(self.w.notifier._t)


class TestUpdateStateMachine(WorkerTestBase):
    def setUp(self):
        super(TestUpdateStateMachine, self).setUp()
        self.worker_context = worker.WorkerContext()

    def test(self):
        w = worker.Worker(0, mock.Mock())
        tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        router_id = 'ac194fc5-f317-412e-8611-fb290629f624'
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


class TestReportStatus(WorkerTestBase):
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
        with mock.patch('akanda.rug.worker.cfg.CONF') as conf:
            self.w.handle_message(
                'debug',
                event.Event('*', '', event.COMMAND,
                            {'payload': {'command': commands.WORKERS_DEBUG}})
            )
            self.assertTrue(conf.log_opt_values.called)


class TestDebugRouters(WorkerTestBase):

    def setUp(self):
        super(TestDebugRouters, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

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
        lock = mock.Mock()
        self.w._router_locks['this-router-id'] = lock
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.ROUTER_MANAGE,
                                     'router_id': 'this-router-id'}}),
        )
        self.assertEqual(set(), self.w._debug_routers)
        self.assertEqual(lock.release.call_count, 1)

    def testManageNoLock(self):
        self.w._debug_routers = set(['this-router-id'])
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.ROUTER_MANAGE,
                                     'router_id': 'this-router-id'}}),
        )
        self.assertEqual(set(), self.w._debug_routers)

    def testManageUnlocked(self):
        self.w._debug_routers = set(['this-router-id'])
        lock = threading.Lock()
        self.w._router_locks['this-router-id'] = lock
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'payload': {'command': commands.ROUTER_MANAGE,
                                     'router_id': 'this-router-id'}}),
        )
        self.assertEqual(set(), self.w._debug_routers)

    def testDebugging(self):
        self.w._debug_routers = set(['ac194fc5-f317-412e-8611-fb290629f624'])

        tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        router_id = 'ac194fc5-f317-412e-8611-fb290629f624'
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


class TestIgnoreRouters(WorkerTestBase):

    def setUp(self):
        super(TestIgnoreRouters, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

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
        fullname = os.path.join(tmpdir, 'ac194fc5-f317-412e-8611-fb290629f624')
        with open(fullname, 'a'):
            os.utime(fullname, None)
        self.addCleanup(lambda: os.unlink(fullname) and os.rmdir(tmpdir))
        w = worker.Worker(0, mock.Mock(), ignore_directory=tmpdir)

        tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        router_id = 'ac194fc5-f317-412e-8611-fb290629f624'
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


class TestDebugTenants(WorkerTestBase):

    def setUp(self):
        super(TestDebugTenants, self).setUp()

        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

        self.w = worker.Worker(0, mock.Mock())

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
        self.w._debug_tenants = set(['98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'])

        tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        router_id = 'ac194fc5-f317-412e-8611-fb290629f624'
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


class TestConfigReload(WorkerTestBase):
    def test(self):
        tenant_id = '*'
        router_id = '*'
        msg = event.Event(
            tenant_id=tenant_id,
            router_id=router_id,
            crud=event.COMMAND,
            body={
                'payload': {'command': commands.CONFIG_RELOAD},
            },
        )
        self.w.handle_message(tenant_id, msg)
        self.assertTrue(self.conf.called)
        self.assertTrue(self.conf.log_opt_values.called)


class TestNormalizeUUID(unittest.TestCase):

    def test_upper(self):
        self.assertEqual(
            'ac194fc5-f317-412e-8611-fb290629f624',
            worker._normalize_uuid(
                'ac194fc5-f317-412e-8611-fb290629f624'.upper()
            )
        )

    def test_no_dashes(self):
        self.assertEqual(
            'ac194fc5-f317-412e-8611-fb290629f624',
            worker._normalize_uuid(
                'ac194fc5f317412e8611fb290629f624'
            )
        )


class TestReleaseLock(WorkerTestBase):
    def test__release_router_lock(self):
        router_id = '0ae77286-c0d6-11e5-9181-525400137dfc'
        fake_lock = mock.Mock(release=mock.Mock())

        self.w._router_locks = {
            router_id: fake_lock
        }
        fake_sm = mock.Mock(router_id=router_id)
        self.w._release_router_lock(fake_sm)
        self.assertTrue(fake_lock.release.called)

    def test__release_router_lock_unlocked(self):
        router_id = '0ae77286-c0d6-11e5-9181-525400137dfc'
        fake_lock = mock.Mock(release=mock.Mock())
        fake_lock.release.side_effect = threading.ThreadError()
        self.w._router_locks = {
            router_id: fake_lock
        }
        fake_sm = mock.Mock(router_id=router_id)
        # just ensure we dont raise
        self.w._release_router_lock(fake_sm)
