# Copyright (c) 2015 Akanda, Inc. All Rights Reserved.
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

import mock
import six

from neutronclient.common import exceptions as neutron_exceptions

from astara import event
from astara.api import neutron
from astara.drivers import router, states

from astara.test.unit import base, fakes


class RouterDriverTest(base.RugTestBase):
    def setUp(self):
        super(RouterDriverTest, self).setUp()

        self.router_id = 'fake_router_id'
        self.image_uuid = 'fake_router_image_uuid'
        self.flavor = 'fake_router_flavor'
        self.mgt_port = '5555'
        self.ctx = mock.Mock()

        self.config(group='router', image_uuid=self.image_uuid)
        self.config(group='router', instance_flavor=self.flavor)
        self.config(group='router', mgt_service_port=self.mgt_port)

        self.ctx = fakes.fake_worker_context()
        self.addCleanup(mock.patch.stopall)

    def _init_driver(self):
        return router.Router(
            worker_context=self.ctx,
            id=self.router_id,
        )

    @mock.patch('astara.drivers.router.Router.post_init')
    def test_init(self, mock_post_init):
        rtr = self._init_driver()
        rtr.post_init = mock.Mock()
        self.assertEqual(
            rtr.name,
            'ak-%s-%s' % (rtr.RESOURCE_NAME, self.router_id))
        mock_post_init.assert_called_with(self.ctx)

    @mock.patch('astara.drivers.router.Router._ensure_cache')
    def test_post_init(self, mock_ensure_cache):
        rtr = self._init_driver()
        rtr.post_init(self.ctx)
        self.assertEqual(rtr.image_uuid, self.image_uuid)
        self.assertEqual(rtr.flavor, self.flavor)
        self.assertEqual(rtr.mgt_port, self.mgt_port)
        mock_ensure_cache.assert_called_with(self.ctx)

    def test__ensure_cache_no_router(self):
        self.ctx.neutron.get_router_detail.return_value = None
        rtr = self._init_driver()
        self.assertIsNone(rtr._router)

    def test__ensure_cache_with_router(self):
        rtr = self._init_driver()
        self.ctx.neutron.get_router_detail.return_value = 'fake_router'
        rtr._ensure_cache(self.ctx)
        self.assertEqual(rtr._router, 'fake_router')

    def test_ports_no_router(self):
        rtr = self._init_driver()
        self.assertEqual(rtr.ports, [])

    def test_ports_with_router(self):
        rtr = self._init_driver()
        fake_router_obj = fakes.fake_router()
        rtr._router = fake_router_obj
        self.assertEqual(set(rtr.ports), set(fake_router_obj.ports))

    @mock.patch('astara.drivers.router.Router.pre_plug')
    def test_pre_boot(self, mock_pre_plug):
        rtr = self._init_driver()
        rtr.pre_boot(self.ctx)
        mock_pre_plug.assert_called_with(self.ctx)

    @mock.patch('astara.api.config.router.build_config')
    @mock.patch('astara.drivers.router.Router._ensure_cache')
    def test_build_config(self, mock_ensure_cache, mock_build_config):
        rtr = self._init_driver()
        fake_router_obj = fakes.fake_router()
        fake_mgt_port = mock.Mock()
        fake_iface_map = mock.Mock()
        rtr._router = fake_router_obj
        mock_build_config.return_value = 'fake_config'
        res = rtr.build_config(self.ctx, fake_mgt_port, fake_iface_map)
        self.assertTrue(mock_ensure_cache.called)
        mock_build_config.return_value = 'fake_config'
        mock_build_config.assert_called_with(
            self.ctx, rtr._router, fake_mgt_port, fake_iface_map)
        self.assertEqual(res, 'fake_config')

    @mock.patch('astara.api.astara_client.update_config')
    def test_update_config(self, mock_update_config):
        rtr = self._init_driver()
        rtr.update_config(management_address='10.0.0.1', config='fake_config')
        mock_update_config.assert_called_with(
            '10.0.0.1',
            rtr.mgt_port,
            'fake_config',)

    @mock.patch('astara.drivers.router.Router._ensure_cache')
    def test_make_ports(self, mock_ensure_cache):
        rtr = self._init_driver()
        fake_router_obj = fakes.fake_router()
        rtr._router = fake_router_obj
        self.ctx.neutron.create_management_port.return_value = 'fake_mgt_port'
        self.ctx.neutron.create_vrrp_port.side_effect = [
            'fake_port_%s' % p.network_id for p in fake_router_obj.ports
        ]
        callback = rtr.make_ports(self.ctx)
        res = callback()
        expected_instance_ports = [
            'fake_port_%s' % p.network_id for p in fake_router_obj.ports
        ]
        self.assertEqual(res, ('fake_mgt_port', expected_instance_ports))

    def test_delete_ports(self):
        rtr = self._init_driver()
        fake_router_obj = fakes.fake_router()
        rtr._router = fake_router_obj
        rtr.delete_ports(self.ctx)
        expected_ports = [mock.call(rtr.id),
                          mock.call(rtr.id, label='MGT')]
        self.ctx.neutron.delete_vrrp_port.assert_has_calls(expected_ports)

    @mock.patch('astara.api.neutron.Neutron')
    def test_pre_populate_retry_loop(self, mocked_neutron_api):
        neutron_client = mock.Mock()
        returned_value = [Exception, []]
        neutron_client.get_routers.side_effect = returned_value

        mocked_neutron_api.return_value = neutron_client
        rtr = self._init_driver()
        with mock.patch('time.sleep'):
            rtr.pre_populate_hook()
        self.assertEqual(
            neutron_client.get_routers.call_args_list,
            [
                mock.call(detailed=False)
                for value in six.moves.range(len(returned_value))
            ]
        )
        self.assertEqual(
            neutron_client.get_routers.call_count,
            len(returned_value)
        )

    def _exit_loop_bad_auth(self, mocked_neutron_api, log, exc):
        neutron_client = mock.Mock()
        neutron_client.get_routers.side_effect = exc
        mocked_neutron_api.return_value = neutron_client
        rtr = self._init_driver()
        rtr.pre_populate_hook()
        log.warning.assert_called_once_with(
            'PrePopulateWorkers thread failed: %s',
            mock.ANY
        )

    @mock.patch('astara.drivers.router.LOG')
    @mock.patch('astara.api.neutron.Neutron')
    def test_pre_populate_unauthorized(self, mocked_neutron_api, log):
        exc = neutron_exceptions.Unauthorized
        self._exit_loop_bad_auth(mocked_neutron_api, log, exc)

    @mock.patch('astara.drivers.router.LOG')
    @mock.patch('astara.api.neutron.Neutron')
    def test_pre_populate_forbidden(self, mocked_neutron_api, log):
        exc = neutron_exceptions.Forbidden
        self._exit_loop_bad_auth(mocked_neutron_api, log, exc)

    @mock.patch('astara.drivers.router.LOG.warning')
    @mock.patch('astara.drivers.router.LOG.debug')
    @mock.patch('astara.api.neutron.Neutron')
    def test_pre_populate_retry_loop_logging(
            self, mocked_neutron_api, log_debug, log_warning):
        neutron_client = mock.Mock()
        message = mock.Mock(tenant_id='1', id='2')
        returned_value = [
            neutron_exceptions.NeutronClientException,
            [message]
        ]
        neutron_client.get_routers.side_effect = returned_value

        mocked_neutron_api.return_value = neutron_client

        rtr = self._init_driver()
        with mock.patch('time.sleep'):
            res = rtr.pre_populate_hook()
        self.assertEqual(2, log_warning.call_count)

        expected_resource = event.Resource(
            driver=rtr.RESOURCE_NAME,
            id='2',
            tenant_id='1',
        )
        self.assertEqual(res, [expected_resource])

    def test_get_resource_id_for_tenant(self):
        fake_router = fakes.fake_router()
        self.ctx.neutron.get_router_for_tenant.return_value = fake_router
        res = router.Router.get_resource_id_for_tenant(
            self.ctx, 'fake_tenant_id', 'fake_message')
        self.assertEqual(res, fake_router.id)
        self.ctx.neutron.get_router_for_tenant.assert_called_with(
            'fake_tenant_id')

    def test_get_resource_id_for_tenant_no_router(self):
        self.ctx.neutron.get_router_for_tenant.return_value = None
        res = router.Router.get_resource_id_for_tenant(
            self.ctx, 'fake_tenant_id', 'fake_message')
        self.assertIsNone(res)
        self.ctx.neutron.get_router_for_tenant.assert_called_with(
            'fake_tenant_id')

    def _test_notification(self, event_type, payload, expected):
        tenant_id = 'fake_tenant_id'
        res = router.Router.process_notification(
            tenant_id, event_type, payload)
        self.assertEqual(res, expected)

    def test_process_notifications_floatingips(self):
        payload = {'router': {'id': 'fake_router_id'}}
        r = event.Resource(
            driver=router.Router.RESOURCE_NAME,
            id='fake_router_id',
            tenant_id='fake_tenant_id')
        e = event.Event(
            resource=r,
            crud=event.UPDATE,
            body=payload,
        )

        events = [
            'floatingip.create.end',
            'floatingip.update.end',
            'floatingip.change.end',
            'floatingip.delete.end']
        [self._test_notification(fipe, payload, e) for fipe in events]

    def test_process_notification_routerstatus(self):
        self._test_notification('routerstatus.update', {}, None)

    def test_process_notification_router_create(self):
        payload = {'router': {'id': 'fake_router_id'}}
        r = event.Resource(
            driver=router.Router.RESOURCE_NAME,
            id='fake_router_id',
            tenant_id='fake_tenant_id')
        e = event.Event(
            resource=r,
            crud=event.CREATE,
            body=payload,
        )
        self._test_notification('router.create.end', payload, e)

    def test_process_notification_router_delete(self):
        payload = {'router_id': 'fake_router_id'}
        r = event.Resource(
            driver=router.Router.RESOURCE_NAME,
            id='fake_router_id',
            tenant_id='fake_tenant_id')
        e = event.Event(
            resource=r,
            crud=event.DELETE,
            body=payload,
        )
        self._test_notification('router.delete.end', payload, e)

    def test_process_notification_interface_notifications(self):
        for notification in router._ROUTER_INTERFACE_NOTIFICATIONS:
            payload = {'router.interface': {'id': 'fake_router_id'}}
            r = event.Resource(
                driver=router.Router.RESOURCE_NAME,
                id='fake_router_id',
                tenant_id='fake_tenant_id')
            e = event.Event(
                resource=r,
                crud=event.UPDATE,
                body=payload,
            )
            self._test_notification(notification, payload, e)

    def test_process_notification_interesting_notifications(self):
        for notification in router._ROUTER_INTERESTING_NOTIFICATIONS:
            payload = {'router': {'id': 'fake_router_id'}}
            r = event.Resource(
                driver=router.Router.RESOURCE_NAME,
                id='fake_router_id',
                tenant_id='fake_tenant_id')
            e = event.Event(
                resource=r,
                crud=event.UPDATE,
                body=payload,
            )
            self._test_notification(notification, payload, e)

    def test_process_notification_not_subscribed(self):
        payload = {'router': {'id': 'fake_router_id'}}
        self._test_notification('whocares.about.this', payload, None)

    @mock.patch('astara.drivers.router.Router._ensure_cache')
    def test_get_state_no_router(self, mock_ensure_cache):
        rtr = self._init_driver()
        rtr._router = None
        self.assertEqual(
            rtr.get_state(self.ctx),
            states.GONE,
        )
        mock_ensure_cache.assert_called_with(self.ctx)

    @mock.patch('astara.drivers.router.Router._ensure_cache')
    def test_get_state(self, mock_ensure_cache):
        rtr = self._init_driver()
        fake_router = fakes.fake_router()
        rtr._router = fake_router
        self.assertEqual(
            rtr.get_state(self.ctx),
            fake_router.status,
        )
        mock_ensure_cache.assert_called_with(self.ctx)

    @mock.patch('astara.drivers.router.Router._ensure_cache')
    def test_synchronize_state_no_router(self, mock_ensure_cache):
        rtr = self._init_driver()
        rtr._router = None
        rtr.synchronize_state(self.ctx, states.DOWN)
        mock_ensure_cache.assert_called_with(self.ctx)
        self.assertFalse(self.ctx.neutron.update_router_status.called)

    @mock.patch('astara.drivers.router.Router._ensure_cache')
    def test_synchronize_state(self, mock_ensure_cache):
        rtr = self._init_driver()
        fake_router_obj = fakes.fake_router()
        rtr._router = fake_router_obj
        rtr.synchronize_state(self.ctx, states.CONFIGURED)
        mock_ensure_cache.assert_called_with(self.ctx)
        self.ctx.neutron.update_router_status.assert_called_with(
            rtr.id,
            'ACTIVE',
        )
        self.assertEqual(rtr._last_synced_status, 'ACTIVE')

    @mock.patch('astara.drivers.router.Router._ensure_cache')
    def test_synchronize_state_no_change(self, mock_ensure_cache):
        rtr = self._init_driver()
        fake_router_obj = fakes.fake_router()
        rtr._router = fake_router_obj
        rtr._last_synced_status = 'ACTIVE'
        rtr.synchronize_state(self.ctx, states.CONFIGURED)
        mock_ensure_cache.assert_called_with(self.ctx)
        self.assertFalse(self.ctx.neutron.update_router_status.called)

    @mock.patch('astara.api.astara_client.get_interfaces')
    def test_get_interfaces(self, mock_get_interfaces):
        mock_get_interfaces.return_value = ['fake_interface']
        rtr = self._init_driver()
        self.assertEqual(
            rtr.get_interfaces('fake_mgt_addr'), ['fake_interface'])
        mock_get_interfaces.assert_called_with(
            'fake_mgt_addr', self.mgt_port)

    @mock.patch('astara.api.astara_client.is_alive')
    def test_is_alive(self, mock_is_alive):
        mock_is_alive.return_value = False
        rtr = self._init_driver()
        self.assertFalse(rtr.is_alive('fake_mgt_addr'))
        mock_is_alive.assert_called_with(
            'fake_mgt_addr', self.mgt_port)

    def test_post_boot(self):
        self._init_driver().post_boot(self.ctx)

    def test__ensure_cache(self):
        rtr = self._init_driver()
        self.ctx.neutron.get_router_detail.return_value = 'fake_router'
        rtr._ensure_cache(self.ctx)
        self.assertEqual(rtr._router, 'fake_router')
        self.ctx.neutron.get_router_detail.assert_called_with(rtr.id)

    def test__ensure_cache_not_found(self):
        rtr = self._init_driver()
        self.ctx.neutron.get_router_detail.side_effect = [neutron.RouterGone]
        rtr._ensure_cache(self.ctx)
        self.assertIsNone(rtr._router)
        self.ctx.neutron.get_router_detail.assert_called_with(rtr.id)
