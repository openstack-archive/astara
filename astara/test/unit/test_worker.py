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
from oslo_config import cfg
import unittest2 as unittest

from astara import commands
from astara import event
from astara import notifications
from astara.api import neutron
from astara.drivers import router
from astara import worker

from astara.common.hash_ring import DC_KEY

from astara.test.unit.db import base


class FakeFetchedResource(object):
    id = 'fake_fetched_resource_id'


class WorkerTestBase(base.DbTestCase):
    tenant_id = '1040f478-3c74-11e5-a72a-173606e0a6d0'
    router_id = '18ffa532-3c74-11e5-a0e7-eb9f90a17ffb'

    def setUp(self):
        super(WorkerTestBase, self).setUp()
        cfg.CONF.boot_timeout = 1
        cfg.CONF.akanda_mgt_service_port = 5000
        cfg.CONF.max_retries = 3
        cfg.CONF.management_prefix = 'fdca:3ba5:a17a:acda::/64'
        cfg.CONF.num_worker_threads = 0

        self.fake_nova = mock.patch('astara.worker.nova').start()
        fake_neutron_obj = mock.patch.object(
            neutron, 'Neutron', autospec=True).start()
        fake_neutron_obj.get_ports_for_instance.return_value = (
            'mgt_port', ['ext_port', 'int_port'])
        fake_neutron_obj.get_router_for_tenant.return_value = (
            FakeFetchedResource())
        self.fake_neutron = mock.patch.object(
            neutron, 'Neutron', return_value=fake_neutron_obj).start()

        self.w = worker.Worker(mock.Mock())
        self.addCleanup(mock.patch.stopall)

        self.target = self.tenant_id
        r = event.Resource(
            tenant_id=self.tenant_id,
            id=self.router_id,
            driver=router.Router.RESOURCE_NAME,
        )
        self.msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )

    def tearDown(self):
        self.w._shutdown()
        super(WorkerTestBase, self).tearDown()

    def enable_debug(self, resource_id=None, tenant_id=None):
        if resource_id:
            self.dbapi.enable_resource_debug(resource_uuid=resource_id)
            is_debug, _ = self.dbapi.resource_in_debug(resource_id)
        if tenant_id:
            self.dbapi.enable_tenant_debug(tenant_uuid=tenant_id)
            is_debug, _ = self.dbapi.tenant_in_debug(tenant_id)
        self.assertTrue(is_debug)

    def assert_not_in_debug(self, resource_id=None, tenant_id=None):
        if resource_id:
            is_debug, _ = self.dbapi.resource_in_debug(resource_id)
            in_debug = self.dbapi.resources_in_debug()
            uuid = resource_id
        if tenant_id:
            is_debug, _ = self.dbapi.tenant_in_debug(tenant_id)
            in_debug = self.dbapi.tenants_in_debug()
            uuid = tenant_id
        self.assertFalse(is_debug)
        self.assertNotIn(uuid, in_debug)


class TestWorker(WorkerTestBase):
    tenant_id = '1040f478-3c74-11e5-a72a-173606e0a6d0'
    resource_id = '18ffa532-3c74-11e5-a0e7-eb9f90a17ffb'
    driver = router.Router.RESOURCE_NAME
    resource = None

    def setUp(self):
        super(TestWorker, self).setUp()
        self.config(enabled=True, group='coordination')
        self.target = self.tenant_id
        self.resource = event.Resource(
            self.driver,
            self.resource_id,
            self.tenant_id)
        self.msg = event.Event(
            resource=self.resource,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.fake_cache = worker.TenantResourceCache()
        self.fake_cache.get_by_tenant = mock.MagicMock()
        self.w.resource_cache = self.fake_cache

    def test__should_process_message_global_debug(self):
        self.dbapi.enable_global_debug()
        self.assertFalse(
            self.w._should_process_message(self.target, self.msg))

    def test__should_process_message_tenant_debug(self):
        self.dbapi.enable_tenant_debug(tenant_uuid=self.tenant_id)
        self.assertFalse(
            self.w._should_process_message(self.target, self.msg))

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_no_router_id(self, fake_hash):
        fake_ring_manager = fake_hash.HashRingManager()
        fake_ring_manager.ring.get_hosts.return_value = [self.w.host]
        self.w.hash_ring_mgr = fake_ring_manager
        self.fake_cache.get_by_tenant.return_value = (
            '9846d012-3c75-11e5-b476-8321b3ff1a1d')
        r = event.Resource(
            driver=router.Router.RESOURCE_NAME,
            id=None,
            tenant_id='fake_tenant_id',
        )
        expected_r = event.Resource(
            driver=router.Router.RESOURCE_NAME,
            id='9846d012-3c75-11e5-b476-8321b3ff1a1d',
            tenant_id='fake_tenant_id',
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        expected = event.Event(
            resource=expected_r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.assertEquals(
            expected,
            self.w._should_process_message(self.target, msg))

    def test__should_process_no_router_id_no_router_found(self):
        self.fake_cache.get_by_tenant.return_value = None
        r = event.Resource(
            driver=router.Router.RESOURCE_NAME,
            id=None,
            tenant_id='fake_tenant_id',
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.assertFalse(self.w._should_process_message(self.target, msg))

    @mock.patch('astara.worker.Worker._deliver_message')
    @mock.patch('astara.worker.Worker._should_process_message')
    def test_handle_message_should_process(self, fake_should_process,
                                           fake_deliver):
        # ensure we plumb through the return of should_process to
        # deliver_message, in case some processing has been done on
        # it
        new_msg = event.Event(
            resource=self.resource,
            crud=event.CREATE,
            body={'key': 'value'},
        )

        fake_should_process.return_value = new_msg
        self.w.handle_message(self.target, self.msg)
        fake_deliver.assert_called_with(self.target, new_msg)
        fake_should_process.assert_called_with(self.target, self.msg)

    @mock.patch('astara.worker.Worker._deliver_message')
    @mock.patch('astara.worker.Worker._should_process_message')
    def test_handle_message_should_not_process(self, fake_should_process,
                                               fake_deliver):
        fake_should_process.return_value = False
        self.w.handle_message(self.target, self.msg)
        self.assertFalse(fake_deliver.called)
        fake_should_process.assert_called_with(self.target, self.msg)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_message_does_not_hash(self, fake_hash):
        fake_ring_manager = fake_hash.HashRingManager()
        fake_ring_manager.ring.get_hosts.return_value = ['not_this_host']
        self.w.hash_ring_mgr = fake_ring_manager
        self.assertFalse(
            self.w._should_process_message(self.target, self.msg))
        fake_ring_manager.ring.get_hosts.assert_called_with(self.router_id)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_message_wildcard_true(self, fake_hash):
        fake_ring_manager = fake_hash.HashRingManager()
        fake_ring_manager.ring.get_hosts.return_value = ['not_this_host']
        self.w.hash_ring_mgr = fake_ring_manager
        self.assertTrue(
            self.w._should_process_message('*', self.msg))
        self.assertFalse(fake_ring_manager.ring.called)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_message_true(self, fake_hash):
        fake_ring_manager = fake_hash.HashRingManager()
        fake_ring_manager.ring.get_hosts.return_value = [self.w.host]
        self.w.hash_ring_mgr = fake_ring_manager
        self.assertEqual(
            self.w._should_process_message(self.target, self.msg),
            self.msg)
        fake_ring_manager.ring.get_hosts.assert_called_with(self.router_id)

    def test__should_process_command_debug_config(self):
        for cmd in [commands.WORKERS_DEBUG, commands.CONFIG_RELOAD]:
            r = event.Resource(
                tenant_id=self.tenant_id,
                id=self.router_id,
                driver='router',
            )
            msg = event.Event(
                resource=r,
                crud=event.COMMAND,
                body={'command': cmd},
            )
            self.assertTrue(self.w._should_process_command(msg))

    def _test__should_process_command(self, fake_hash, cmds, key,
                                      negative=False):
        self.config(enabled=True, group='coordination')
        fake_ring_manager = fake_hash.HashRingManager()

        if not negative:
            fake_ring_manager.ring.get_hosts.return_value = [self.w.host]
            assertion = self.assertTrue
        else:
            fake_ring_manager.ring.get_hosts.return_value = ['not_this_host']
            assertion = self.assertFalse

        self.w.hash_ring_mgr = fake_ring_manager
        for cmd in cmds:
            r = event.Resource(
                tenant_id=self.tenant_id,
                id=self.router_id,
                driver='router',
            )
            msg = event.Event(
                resource=r,
                crud=event.COMMAND,
                body={
                    'command': cmd,
                    'resource_id': self.router_id,
                    'router_id': self.router_id,  # compat.
                    'tenant_id': self.tenant_id}
            )
            assertion(self.w._should_process_command(msg))

            if key == DC_KEY:
                fake_ring_manager.ring.get_hosts.assert_called_with(DC_KEY)
            else:
                fake_ring_manager.ring.get_hosts.assert_called_with(
                    msg.body[key])

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_command_resources(self, fake_hash):
        cmds = worker.EVENT_COMMANDS
        self._test__should_process_command(
            fake_hash, cmds=cmds, key='resource_id', negative=False)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_command_resources_negative(self, fake_hash):
        cmds = [commands.RESOURCE_DEBUG, commands.RESOURCE_MANAGE]
        self._test__should_process_command(
            fake_hash, cmds=cmds, key='resource_id', negative=True)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_command_routers(self, fake_hash):
        cmds = [commands.ROUTER_DEBUG, commands.ROUTER_MANAGE]
        self._test__should_process_command(
            fake_hash, cmds=cmds, key='router_id', negative=False)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_command_routers_negative(self, fake_hash):
        cmds = [commands.ROUTER_DEBUG, commands.ROUTER_MANAGE]
        self._test__should_process_command(
            fake_hash, cmds=cmds, key='router_id', negative=True)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_command_tenants(self, fake_hash):
        cmds = [commands.TENANT_DEBUG, commands.TENANT_MANAGE]
        self._test__should_process_command(
            fake_hash, cmds=cmds, key='tenant_id', negative=False)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_command_tenants_negative(self, fake_hash):
        cmds = [commands.TENANT_DEBUG, commands.TENANT_MANAGE]
        self._test__should_process_command(
            fake_hash, cmds=cmds, key='tenant_id', negative=True)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_command_global_debug(self, fake_hash):
        fake_hash.DC_KEY = DC_KEY
        cmds = [commands.GLOBAL_DEBUG]
        self._test__should_process_command(
            fake_hash, cmds=cmds, key=DC_KEY, negative=False)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test__should_process_command_global_debug_negative(self, fake_hash):
        fake_hash.DC_KEY = DC_KEY
        cmds = [commands.GLOBAL_DEBUG]
        self._test__should_process_command(
            fake_hash, cmds=cmds, key=DC_KEY, negative=True)


class TestResourceCache(WorkerTestBase):
    def setUp(self):
        super(TestResourceCache, self).setUp()
        self.resource_cache = worker.TenantResourceCache()
        self.worker_context = worker.WorkerContext()

    def test_resource_cache_hit(self):
        self.resource_cache._tenant_resources = {
            router.Router.RESOURCE_NAME: {
                'fake_tenant_id': 'fake_cached_resource_id',
            }
        }
        r = event.Resource(
            tenant_id='fake_tenant_id',
            id='fake_resource_id',
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(resource=r, crud=event.UPDATE, body={})
        res = self.resource_cache.get_by_tenant(
            resource=r, worker_context=self.worker_context, message=msg)
        self.assertEqual(res, 'fake_cached_resource_id')
        self.assertFalse(self.w._context.neutron.get_router_for_tenant.called)

    def test_resource_cache_miss(self):
        r = event.Resource(
            tenant_id='fake_tenant_id',
            id='fake_fetched_resource_id',
            driver=router.Router.RESOURCE_NAME,
        )
        msg = event.Event(
            resource=r,
            crud=event.UPDATE,
            body={},
        )
        res = self.resource_cache.get_by_tenant(
            resource=r,
            worker_context=self.worker_context,
            message=msg)
        self.assertEqual(res, 'fake_fetched_resource_id')
        self.w._context.neutron.get_router_for_tenant.assert_called_with(
            'fake_tenant_id')


class TestCreatingResource(WorkerTestBase):
    def setUp(self):
        super(TestCreatingResource, self).setUp()
        self.tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        self.router_id = 'ac194fc5-f317-412e-8611-fb290629f624'
        self.hostname = 'akanda'

        self.resource = event.Resource(router.Router.RESOURCE_NAME,
                                       self.router_id,
                                       self.tenant_id)

        self.msg = event.Event(
            resource=self.resource,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.w._should_process_message = mock.MagicMock(return_value=self.msg)

    def test_in_tenant_managers(self):
        self.w.handle_message(self.tenant_id, self.msg)
        self.assertIn(self.tenant_id, self.w.tenant_managers)
        trm = self.w.tenant_managers[self.tenant_id]
        self.assertEqual(self.tenant_id, trm.tenant_id)

    def test_not_in_tenant_managers(self):
        self.w._should_process_message = mock.MagicMock(return_value=False)
        self.w.handle_message(self.tenant_id, self.msg)
        self.assertNotIn(self.tenant_id, self.w.tenant_managers)

    def test_message_enqueued(self):
        self.w.handle_message(self.tenant_id, self.msg)
        trm = self.w.tenant_managers[self.tenant_id]
        sm = trm.get_state_machines(self.msg, worker.WorkerContext())[0]
        self.assertEqual(len(sm._queue), 1)


class TestWildcardMessages(WorkerTestBase):

    def setUp(self):
        super(TestWildcardMessages, self).setUp()

        self.tenant_id_1 = 'a8f964d4-6631-11e5-a79f-525400cfc32a'
        self.tenant_id_2 = 'ef1a6e90-6631-11e5-83cb-525400cfc326'
        self.w._should_process_message = mock.MagicMock(return_value=self.msg)

        # Create some tenants
        for msg in [
                event.Event(
                    resource=event.Resource(
                        driver=router.Router.RESOURCE_NAME,
                        id='ABCD',
                        tenant_id=self.tenant_id_1,
                    ),
                    crud=event.CREATE,
                    body={'key': 'value'},
                ),
                event.Event(
                    resource=event.Resource(
                        driver=router.Router.RESOURCE_NAME,
                        id='EFGH',
                        tenant_id=self.tenant_id_2),
                    crud=event.CREATE,
                    body={'key': 'value'},
                )]:
            self.w.handle_message(msg.resource.tenant_id, msg)

    def test_wildcard_to_all(self):
        trms = self.w._get_trms('*')
        ids = sorted(trm.tenant_id for trm in trms)
        self.assertEqual(ids, [self.tenant_id_1, self.tenant_id_2])

    def test_wildcard_to_error(self):
        trms = self.w._get_trms('error')
        ids = sorted(trm.tenant_id for trm in trms)
        self.assertEqual(ids, [self.tenant_id_1, self.tenant_id_2])


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
        self.w._should_process_message = mock.MagicMock(return_value=self.msg)

    def _test(self, fake_hash, negative=False):
        self.config(enabled=True, group='coordination')
        fake_ring_manager = fake_hash.HashRingManager()
        if not negative:
            fake_ring_manager.ring.get_hosts.return_value = [self.w.host]
        else:
            fake_ring_manager.ring.get_hosts.return_value = []

        self.w.hash_ring_mgr = fake_ring_manager

        # Create the router manager and state machine so we can
        # replace the update() method with a mock.
        trm = self.w._get_trms(self.tenant_id)[0]
        sm = trm.get_state_machines(self.msg, self.worker_context)[0]
        with mock.patch.object(sm, 'update') as meth:
            self.w.handle_message(self.tenant_id, self.msg)
            # Add a null message so the worker loop will exit. We have
            # to do this directly, because if we do it through
            # handle_message() that triggers shutdown logic that keeps
            # the loop from working properly.
            self.w.work_queue.put(None)
            # We aren't using threads (and we trust that threads do
            # work) so we just invoke the thread target ourselves to
            # pretend.
            used_context = self.w._thread_target()

            if not negative:
                meth.assert_called_once_with(used_context)
            else:
                self.assertFalse(meth.called)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test_host_mapped(self, fake_hash):
        self._test(fake_hash)

    @mock.patch('astara.worker.hash_ring', autospec=True)
    def test_host_not_mapped(self, fake_hash):
        self._test(fake_hash, negative=True)


class TestReportStatus(WorkerTestBase):
    def test_report_status_dispatched(self):
        with mock.patch.object(self.w, 'report_status') as meth:
            self.w.handle_message(
                'debug',
                event.Event('*', event.COMMAND,
                            {'command': commands.WORKERS_DEBUG})
            )
            meth.assert_called_once_with()

    def test_handle_message_report_status(self):
        with mock.patch('astara.worker.cfg.CONF') as conf:
            self.w.handle_message(
                'debug',
                event.Event('*', event.COMMAND,
                            {'command': commands.WORKERS_DEBUG})
            )
            self.assertTrue(conf.log_opt_values.called)


class TestDebugRouters(WorkerTestBase):
    def setUp(self):
        super(TestDebugRouters, self).setUp()
        self.w._should_process_command = mock.MagicMock(return_value=self.msg)

    def testNoDebugs(self):
        self.assertEqual(self.dbapi.resources_in_debug(), set())

    def testWithDebugs(self):
        self.w.handle_message(
            '*',
            event.Event('*', event.COMMAND,
                        {'command': commands.RESOURCE_DEBUG,
                         'resource_id': 'this-resource-id',
                         'reason': 'foo'}),
        )
        self.enable_debug(resource_id='this-resource-id')
        self.assertIn(('this-resource-id', 'foo'),
                      self.dbapi.resources_in_debug())

    def testManage(self):
        self.enable_debug(resource_id='this-resource-id')
        lock = mock.Mock()
        self.w._resource_locks['this-resource-id'] = lock
        r = event.Resource(
            tenant_id='*',
            id='*',
            driver=None,
        )
        self.w.handle_message(
            '*',
            event.Event(
                resource=r,
                crud=event.COMMAND,
                body={'command': commands.RESOURCE_MANAGE,
                      'resource_id': 'this-resource-id'}),
        )
        self.assert_not_in_debug(resource_id='this-resource-id')
        self.assertEqual(lock.release.call_count, 1)

    def testManageNoLock(self):
        self.enable_debug(resource_id='this-resource-id')
        self.w.handle_message(
            '*',
            event.Event('*', event.COMMAND,
                        {'command': commands.RESOURCE_MANAGE,
                         'resource_id': 'this-resource-id'}),
        )
        self.assert_not_in_debug(resource_id='this-resource-id')

    def testManageUnlocked(self):
        self.enable_debug(resource_id='this-resource-id')
        lock = threading.Lock()
        self.w._resource_locks['this-resource-id'] = lock
        self.w.handle_message(
            '*',
            event.Event('*', event.COMMAND,
                        {'command': commands.RESOURCE_MANAGE,
                         'resource_id': 'this-resource-id'}),
        )
        self.assert_not_in_debug(resource_id='this-resource-id')

    def testDebugging(self):
        tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        resource_id = 'ac194fc5-f317-412e-8611-fb290629f624'
        self.enable_debug(resource_id=resource_id)
        msg = event.Event(
            resource=event.Resource(router.Router.RESOURCE_NAME,
                                    resource_id,
                                    tenant_id),
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
    def setUp(self):
        super(TestDebugTenants, self).setUp()
        self.w._should_process_command = mock.MagicMock(return_value=self.msg)

    def testNoDebugs(self):
        self.assertEqual(self.dbapi.tenants_in_debug(), set())

    def testWithDebugs(self):
        self.enable_debug(tenant_id='this-tenant-id')
        self.w.handle_message(
            '*',
            event.Event('*', event.COMMAND,
                        {'command': commands.TENANT_DEBUG,
                         'tenant_id': 'this-tenant-id'}),
        )
        is_debug, _ = self.dbapi.tenant_in_debug('this-tenant-id')
        self.assertTrue(is_debug)

    def testManage(self):
        self.enable_debug(tenant_id='this-tenant-id')
        self.w.handle_message(
            '*',
            event.Event('*', event.COMMAND,
                        {'command': commands.TENANT_MANAGE,
                         'tenant_id': 'this-tenant-id'}),
        )
        self.assert_not_in_debug(tenant_id='this-tenant-id')

    def testDebugging(self):
        tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        resource_id = 'ac194fc5-f317-412e-8611-fb290629f624'
        self.enable_debug(tenant_id=tenant_id)
        msg = event.Event(
            resource=event.Resource(
                driver=router.Router.RESOURCE_NAME,
                id=resource_id,
                tenant_id=tenant_id),
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
        resource_id = '*'
        msg = event.Event(
            resource=resource_id,
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
        resource_id = 'ac194fc5-f317-412e-8611-fb290629f624'
        msg = event.Event(
            resource=event.Resource(router.Router.RESOURCE_NAME,
                                    resource_id,
                                    tenant_id),
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


class TestRebalance(WorkerTestBase):
    def test_rebalance(self):
        tenant_id = '98dd9c41-d3ac-4fd6-8927-567afa0b8fc3'
        resource_id = 'ac194fc5-f317-412e-8611-fb290629f624'
        r = event.Resource(
            tenant_id=tenant_id,
            id=resource_id,
            driver='router',
        )
        msg = event.Event(
            resource=r,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        trm = self.w._get_trms(tenant_id)[0]
        sm = trm.get_state_machines(msg, worker.WorkerContext())[0]

        self.w.hash_ring_mgr.rebalance(['foo'])
        self.assertEqual(self.w.hash_ring_mgr.hosts, set(['foo']))
        r = event.Resource(
            tenant_id='*',
            id='*',
            driver='*',
        )
        msg = event.Event(
            resource=r,
            crud=event.REBALANCE,
            body={'members': ['foo', 'bar']},
        )
        with mock.patch.object(sm, 'drop_queue') as meth:
            self.w.handle_message('*', msg)
            self.assertTrue(meth.called)
        self.assertEqual(self.w.hash_ring_mgr.hosts, set(['foo', 'bar']))
