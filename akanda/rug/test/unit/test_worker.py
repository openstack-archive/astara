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


import threading

import mock

import unittest2 as unittest

from oslo_config import cfg

from akanda.rug import commands
from akanda.rug import event
from akanda.rug import notifications
from akanda.rug import worker

from akanda.rug.api import neutron


from akanda.rug.test.unit.db import base


class FakeFetchedRouter(object):
    id = 'fake_fetched_router_id'


class WorkerTestBase(base.DbTestCase):
    def setUp(self):
        super(WorkerTestBase, self).setUp()
        cfg.CONF.boot_timeout = 1
        cfg.CONF.akanda_mgt_service_port = 5000
        cfg.CONF.max_retries = 3
        cfg.CONF.management_prefix = 'fdca:3ba5:a17a:acda::/64'
        cfg.CONF.num_worker_threads = 0

        self.fake_nova = mock.patch('akanda.rug.worker.nova').start()
        fake_neutron_obj = mock.patch.object(
            neutron, 'Neutron', autospec=True).start()
        fake_neutron_obj.get_ports_for_instance.return_value = (
            'mgt_port', ['ext_port', 'int_port'])
        fake_neutron_obj.get_router_for_tenant.return_value = (
            FakeFetchedRouter())
        self.fake_neutron = mock.patch.object(
            neutron, 'Neutron', return_value=fake_neutron_obj).start()
        self.w = worker.Worker(mock.Mock())
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        self.w._shutdown()
        super(WorkerTestBase, self).tearDown()

    def enable_debug(self, router_uuid=None, tenant_uuid=None):
        if router_uuid:
            self.dbapi.enable_router_debug(router_uuid=router_uuid)
            is_debug, _ = self.dbapi.router_in_debug(router_uuid)
        if tenant_uuid:
            self.dbapi.enable_tenant_debug(tenant_uuid=tenant_uuid)
            is_debug, _ = self.dbapi.tenant_in_debug(tenant_uuid)
        self.assertTrue(is_debug)

    def assert_not_in_debug(self, router_uuid=None, tenant_uuid=None):
        if router_uuid:
            is_debug, _ = self.dbapi.router_in_debug(router_uuid)
            in_debug = self.dbapi.routers_in_debug()
            uuid = router_uuid
        if tenant_uuid:
            is_debug, _ = self.dbapi.tenant_in_debug(tenant_uuid)
            in_debug = self.dbapi.tenants_in_debug()
            uuid = tenant_uuid
        self.assertFalse(is_debug)
        self.assertNotIn(uuid, in_debug)


class TestWorker(WorkerTestBase):
    tenant_id = '1040f478-3c74-11e5-a72a-173606e0a6d0'
    router_id = '18ffa532-3c74-11e5-a0e7-eb9f90a17ffb'

    def setUp(self):
        super(TestWorker, self).setUp()
        self.target = self.tenant_id
        self.msg = event.Event(
            tenant_id=self.tenant_id,
            router_id=self.router_id,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.fake_router_cache = worker.TenantRouterCache()
        self.fake_router_cache.get_by_tenant = mock.MagicMock()
        self.w.router_cache = self.fake_router_cache

    def test__should_process_true(self):
        self.assertEqual(
            self.msg,
            self.w._should_process(self.msg))

    def test__should_process_global_debug(self):
        self.dbapi.enable_global_debug()
        self.assertFalse(
            self.w._should_process(self.msg))

    def test__should_process_tenant_debug(self):
        self.dbapi.enable_tenant_debug(tenant_uuid=self.tenant_id)
        self.assertFalse(
            self.w._should_process(self.msg))

    def test__should_process_no_router_id(self):
        self.fake_router_cache.get_by_tenant.return_value = (
            '9846d012-3c75-11e5-b476-8321b3ff1a1d')
        msg = event.Event(
            tenant_id=self.tenant_id,
            router_id=None,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        expected = event.Event(
            tenant_id=self.tenant_id,
            router_id='9846d012-3c75-11e5-b476-8321b3ff1a1d',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.assertEquals(expected, self.w._should_process(msg))

    def test__should_process_no_router_id_no_router_found(self):
        self.fake_router_cache.get_by_tenant.return_value = None
        msg = event.Event(
            tenant_id=self.tenant_id,
            router_id=None,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.assertFalse(self.w._should_process(msg))

    def test__populate_router_id_not_needed(self):
        self.assertEqual(
            self.w._populate_router_id(self.msg),
            self.msg,
        )

    def test__populate_router_id(self):
        self.msg = event.Event(
            tenant_id=self.tenant_id,
            router_id=None,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.fake_router_cache.get_by_tenant.return_value = (
            'ccd7048c-3c75-11e5-b6a7-53233f5cf591')
        expected_msg = event.Event(
            tenant_id=self.tenant_id,
            router_id='ccd7048c-3c75-11e5-b6a7-53233f5cf591',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        res = self.w._populate_router_id(self.msg)
        self.assertEqual(res, expected_msg)
        self.fake_router_cache.get_by_tenant.assert_called_with(
            self.tenant_id, self.w._context)

    def test__populate_router_id_not_found(self):
        self.msg = event.Event(
            tenant_id=self.tenant_id,
            router_id=None,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.fake_router_cache.get_by_tenant.return_value = None
        res = self.w._populate_router_id(self.msg)
        self.assertEqual(res, self.msg)
        self.fake_router_cache.get_by_tenant.assert_called_with(
            self.tenant_id, self.w._context)

    @mock.patch('akanda.rug.worker.Worker._deliver_message')
    @mock.patch('akanda.rug.worker.Worker._should_process')
    def test_handle_message_should_process(self, fake_should_process,
                                           fake_deliver):
        # ensure we plumb through the return of should_process to
        # deliver_message, in case some processing has been done on
        # it
        new_msg = event.Event(
            tenant_id='0e50fe44-3c77-11e5-9b4c-d75b3be53047',
            router_id='11df3102-3c77-11e5-9c6f-2fd3b676e508',
            crud=event.CREATE,
            body={'key': 'value'},
        )

        fake_should_process.return_value = new_msg
        self.w.handle_message(self.target, self.msg)
        fake_deliver.assert_called_with(self.target, new_msg)
        fake_should_process.assert_called_with(self.msg)

    @mock.patch('akanda.rug.worker.Worker._deliver_message')
    @mock.patch('akanda.rug.worker.Worker._should_process')
    def test_handle_message_should_not_process(self, fake_should_process,
                                               fake_deliver):
        fake_should_process.return_value = False
        self.w.handle_message(self.target, self.msg)
        self.assertFalse(fake_deliver.called)
        fake_should_process.assert_called_with(self.msg)


class TestRouterCache(WorkerTestBase):
    def setUp(self):
        super(TestRouterCache, self).setUp()
        self.router_cache = worker.TenantRouterCache()
        self.worker_context = worker.WorkerContext()

    def test_router_cache_hit(self):
        self.router_cache._tenant_routers = {
            'fake_tenant_id': 'fake_cached_router_id',
        }
        res = self.router_cache.get_by_tenant(
            tenant_uuid='fake_tenant_id', worker_context=self.worker_context)
        self.assertEqual(res, 'fake_cached_router_id')
        self.assertFalse(self.w._context.neutron.get_router_for_tenant.called)

    def test_router_cache_miss(self):
        res = self.router_cache.get_by_tenant(
            tenant_uuid='fake_tenant_id', worker_context=self.worker_context)
        self.assertEqual(res, 'fake_fetched_router_id')
        self.w._context.neutron.get_router_for_tenant.assert_called_with(
            'fake_tenant_id')


class TestCreatingRouter(WorkerTestBase):
    def setUp(self):
        super(TestCreatingRouter, self).setUp()
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

    def test_in_tenant_managers(self):
        self.assertIn(self.tenant_id, self.w.tenant_managers)
        trm = self.w.tenant_managers[self.tenant_id]
        self.assertEqual(self.tenant_id, trm.tenant_id)

    def test_message_enqueued(self):
        trm = self.w.tenant_managers[self.tenant_id]
        sm = trm.get_state_machines(self.msg, worker.WorkerContext())[0]
        self.assertEqual(len(sm._queue), 1)


class TestWildcardMessages(WorkerTestBase):

    def setUp(self):
        super(TestWildcardMessages, self).setUp()
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

    def test_wildcard_to_all(self):
        trms = self.w._get_trms('*')
        ids = sorted(trm.tenant_id for trm in trms)
        self.assertEqual(ids,
                         ['98dd9c41-d3ac-4fd6-8927-567afa0b8fc3',
                          'ac194fc5-f317-412e-8611-fb290629f624'])

    def test_wildcard_to_error(self):
        trms = self.w._get_trms('error')
        ids = sorted(trm.tenant_id for trm in trms)
        self.assertEqual(ids,
                         ['98dd9c41-d3ac-4fd6-8927-567afa0b8fc3',
                          'ac194fc5-f317-412e-8611-fb290629f624'])


class TestShutdown(WorkerTestBase):
    def test_shutdown_on_null_message(self):
        with mock.patch.object(self.w, '_shutdown') as meth:
            self.w.handle_message(None, None)
            meth.assert_called_once_with()

    def test_stop_threads(self):
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
        notifier = notifications.Publisher('topic')
        w = worker.Worker(notifier)
        self.assertTrue(notifier)
        w._shutdown()
        self.assertFalse(w.notifier._t)


class TestUpdateStateMachine(WorkerTestBase):
    def setUp(self):
        super(TestUpdateStateMachine, self).setUp()
        self.worker_context = worker.WorkerContext()

    def test(self):
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
        trm = self.w._get_trms(tenant_id)[0]
        sm = trm.get_state_machines(msg, self.worker_context)[0]
        with mock.patch.object(sm, 'update') as meth:
            self.w.handle_message(tenant_id, msg)
            # Add a null message so the worker loop will exit. We have
            # to do this directly, because if we do it through
            # handle_message() that triggers shutdown logic that keeps
            # the loop from working properly.
            self.w.work_queue.put(None)
            # We aren't using threads (and we trust that threads do
            # work) so we just invoke the thread target ourselves to
            # pretend.
            used_context = self.w._thread_target()
            meth.assert_called_once_with(used_context)


class TestReportStatus(WorkerTestBase):
    def test_report_status_dispatched(self):
        with mock.patch.object(self.w, 'report_status') as meth:
            self.w.handle_message(
                'debug',
                event.Event('*', '', event.COMMAND,
                            {'command': commands.WORKERS_DEBUG})
            )
            meth.assert_called_once_with()

    def test_handle_message_report_status(self):
        with mock.patch('akanda.rug.worker.cfg.CONF') as conf:
            self.w.handle_message(
                'debug',
                event.Event('*', '', event.COMMAND,
                            {'command': commands.WORKERS_DEBUG})
            )
            self.assertTrue(conf.log_opt_values.called)


class TestDebugRouters(WorkerTestBase):
    def testNoDebugs(self):
        self.assertEqual(self.dbapi.routers_in_debug(), set())

    def testWithDebugs(self):
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'command': commands.ROUTER_DEBUG,
                         'router_id': 'this-router-id',
                         'reason': 'foo'}),
        )
        self.enable_debug(router_uuid='this-router-id')
        self.assertIn(('this-router-id', 'foo'), self.dbapi.routers_in_debug())

    def testManage(self):
        self.enable_debug(router_uuid='this-router-id')
        lock = mock.Mock()
        self.w._router_locks['this-router-id'] = lock
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'command': commands.ROUTER_MANAGE,
                         'router_id': 'this-router-id'}),
        )
        self.assert_not_in_debug(router_uuid='this-router-id')
        self.assertEqual(lock.release.call_count, 1)

    def testManageNoLock(self):
        self.enable_debug(router_uuid='this-router-id')
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'command': commands.ROUTER_MANAGE,
                         'router_id': 'this-router-id'}),
        )
        self.assert_not_in_debug(router_uuid='this-router-id')

    def testManageUnlocked(self):
        self.enable_debug(router_uuid='this-router-id')
        lock = threading.Lock()
        self.w._router_locks['this-router-id'] = lock
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'command': commands.ROUTER_MANAGE,
                         'router_id': 'this-router-id'}),
        )
        self.assert_not_in_debug(router_uuid='this-router-id')

    def testDebugging(self):
        tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        router_id = 'ac194fc5-f317-412e-8611-fb290629f624'
        self.enable_debug(router_uuid=router_id)
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


class TestDebugTenants(WorkerTestBase):
    def testNoDebugs(self):
        self.assertEqual(self.dbapi.tenants_in_debug(), set())

    def testWithDebugs(self):
        self.enable_debug(tenant_uuid='this-tenant-id')
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'command': commands.TENANT_DEBUG,
                         'tenant_id': 'this-tenant-id'}),
        )
        is_debug, _ = self.dbapi.tenant_in_debug('this-tenant-id')
        self.assertTrue(is_debug)

    def testManage(self):
        self.enable_debug(tenant_uuid='this-tenant-id')
        self.w.handle_message(
            '*',
            event.Event('*', '', event.COMMAND,
                        {'command': commands.TENANT_MANAGE,
                         'tenant_id': 'this-tenant-id'}),
        )
        self.assert_not_in_debug(tenant_uuid='this-tenant-id')

    def testDebugging(self):
        tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        router_id = 'ac194fc5-f317-412e-8611-fb290629f624'
        self.enable_debug(tenant_uuid=tenant_id)
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
    @mock.patch.object(worker, 'cfg')
    def test(self, mock_cfg):
        mock_cfg.CONF = mock.MagicMock(
            log_opt_values=mock.MagicMock())
        tenant_id = '*'
        router_id = '*'
        msg = event.Event(
            tenant_id=tenant_id,
            router_id=router_id,
            crud=event.COMMAND,
            body={'command': commands.CONFIG_RELOAD}
        )
        self.w.handle_message(tenant_id, msg)
        self.assertTrue(mock_cfg.CONF.called)
        self.assertTrue(mock_cfg.CONF.log_opt_values.called)


class TestNormalizeUUID(unittest.TestCase):

    def test_upper(self):
        self.assertEqual(
            worker._normalize_uuid(
                'ac194fc5-f317-412e-8611-fb290629f624'.upper()),
            'ac194fc5-f317-412e-8611-fb290629f624')

    def test_no_dashes(self):
        self.assertEqual(
            worker._normalize_uuid('ac194fc5f317412e8611fb290629f624'),
            'ac194fc5-f317-412e-8611-fb290629f624')


class TestGlobalDebug(WorkerTestBase):
    def test_global_debug_no_message_sent(self):
        self.dbapi.enable_global_debug()
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
