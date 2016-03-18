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
from astara.drivers import loadbalancer, states

from astara.test.unit import base, fakes


class LoadBalancerDriverTest(base.RugTestBase):
    def setUp(self):
        super(LoadBalancerDriverTest, self).setUp()

        self.loadbalancer_id = 'fake_loadbalancer_id'
        self.image_uuid = 'fake_loadbalancer_image_uuid'
        self.flavor = 'fake_loadbalancer_flavor'
        self.mgt_port = '5555'
        self.ctx = mock.Mock()

        self.config(group='loadbalancer', image_uuid=self.image_uuid)
        self.config(group='loadbalancer', instance_flavor=self.flavor)
        self.config(group='loadbalancer', mgt_service_port=self.mgt_port)

        self.ctx = fakes.fake_worker_context()
        self.addCleanup(mock.patch.stopall)

    def _init_driver(self):
        return loadbalancer.LoadBalancer(
            worker_context=self.ctx,
            id=self.loadbalancer_id,
        )

    @mock.patch('astara.drivers.loadbalancer.LoadBalancer.post_init')
    def test_init(self, mock_post_init):
        lb = self._init_driver()
        lb.post_init = mock.Mock()
        self.assertEqual(
            lb.name,
            'ak-%s-%s' % (lb.RESOURCE_NAME, self.loadbalancer_id))
        mock_post_init.assert_called_with(self.ctx)

    def test_ports_no_loadbalancer(self):
        lb = self._init_driver()
        self.assertEqual(lb.ports, [])

    def test_ports_with_loadbalancer(self):
        lb = self._init_driver()
        fake_lb = fakes.fake_loadbalancer()
        lb._loadbalancer = fake_lb
        self.assertEqual(set(lb.ports), set(fake_lb.ports))

    def test_pre_boot(self):
        lb = self._init_driver()
        lb.pre_boot(self.ctx)

    def test_post_boot(self):
        lb = self._init_driver()
        lb.post_boot(self.ctx)

    def test_pre_plug(self):
        lb = self._init_driver()
        lb.pre_plug(self.ctx)

    @mock.patch('astara.api.config.loadbalancer.build_config')
    @mock.patch('astara.drivers.loadbalancer.LoadBalancer._ensure_cache')
    def test_build_config(self, mock_ensure_cache, mock_build_config):
        lb = self._init_driver()
        fake_lb = fakes.fake_loadbalancer()
        fake_mgt_port = mock.Mock()
        fake_iface_map = mock.Mock()
        lb._loadbalancer = fake_lb
        mock_build_config.return_value = 'fake_config'
        res = lb.build_config(self.ctx, fake_mgt_port, fake_iface_map)
        self.assertTrue(mock_ensure_cache.called)
        mock_build_config.return_value = 'fake_config'
        mock_build_config.assert_called_with(
            self.ctx.neutron, lb._loadbalancer, fake_mgt_port, fake_iface_map)
        self.assertEqual(res, 'fake_config')

    @mock.patch('astara.api.astara_client.update_config')
    def test_update_config(self, mock_update_config):
        lb = self._init_driver()
        lb.update_config(management_address='10.0.0.1', config='fake_config')
        mock_update_config.assert_called_with(
            '10.0.0.1',
            lb.mgt_port,
            'fake_config',)

    @mock.patch('astara.drivers.loadbalancer.LoadBalancer._ensure_cache')
    def test_make_ports(self, mock_ensure_cache):
        lb = self._init_driver()
        fake_lb = fakes.fake_loadbalancer()
        lb._loadbalancer = fake_lb
        fake_lb_port = mock.Mock(id='fake_lb_port_id')

        self.ctx.neutron.create_management_port.return_value = 'fake_mgt_port'
        self.ctx.neutron.create_vrrp_port.return_value = fake_lb_port
        callback = lb.make_ports(self.ctx)
        res = callback()
        self.assertEqual(res, ('fake_mgt_port', [fake_lb_port]))

    @mock.patch('astara.api.neutron.Neutron')
    def test_pre_populate_retry_loop(self, mocked_neutron_api):
        neutron_client = mock.Mock()
        returned_value = [Exception, []]
        neutron_client.get_loadbalancers.side_effect = returned_value

        mocked_neutron_api.return_value = neutron_client
        lb = self._init_driver()
        with mock.patch('time.sleep'):
            lb.pre_populate_hook()
        self.assertEqual(
            neutron_client.get_loadbalancers.call_args_list,
            [
                mock.call()
                for value in six.moves.range(len(returned_value))
            ]
        )
        self.assertEqual(
            neutron_client.get_loadbalancers.call_count,
            len(returned_value)
        )

    def _exit_loop_bad_auth(self, mocked_neutron_api, log, exc):
        neutron_client = mock.Mock()
        neutron_client.get_loadbalancers.side_effect = exc
        mocked_neutron_api.return_value = neutron_client
        lb = self._init_driver()
        lb.pre_populate_hook()
        log.warning.assert_called_once_with(
            'PrePopulateWorkers thread failed: %s',
            mock.ANY
        )

    @mock.patch('astara.drivers.loadbalancer.LOG')
    @mock.patch('astara.api.neutron.Neutron')
    def test_pre_populate_unauthorized(self, mocked_neutron_api, log):
        exc = neutron_exceptions.Unauthorized
        self._exit_loop_bad_auth(mocked_neutron_api, log, exc)

    @mock.patch('astara.drivers.loadbalancer.LOG')
    @mock.patch('astara.api.neutron.Neutron')
    def test_pre_populate_forbidden(self, mocked_neutron_api, log):
        exc = neutron_exceptions.Forbidden
        self._exit_loop_bad_auth(mocked_neutron_api, log, exc)

    @mock.patch('astara.drivers.loadbalancer.LOG.warning')
    @mock.patch('astara.drivers.loadbalancer.LOG.debug')
    @mock.patch('astara.api.neutron.Neutron')
    def test_pre_populate_retry_loop_logging(
            self, mocked_neutron_api, log_debug, log_warning):
        neutron_client = mock.Mock()
        message = mock.Mock(tenant_id='1', id='2')
        returned_value = [
            neutron_exceptions.NeutronClientException,
            [message]
        ]
        neutron_client.get_loadbalancers.side_effect = returned_value

        mocked_neutron_api.return_value = neutron_client

        lb = self._init_driver()
        with mock.patch('time.sleep'):
            res = lb.pre_populate_hook()
        self.assertEqual(2, log_warning.call_count)

        expected_resource = event.Resource(
            driver=lb.RESOURCE_NAME,
            id='2',
            tenant_id='1',
        )
        self.assertEqual(res, [expected_resource])

    def test_get_resource_id_loadbalancer_msg(self):
        msg = mock.Mock(
            body={'loadbalancer': {'id': 'lb_id'}}
        )
        lb = self._init_driver()
        self.assertEqual(
            lb.get_resource_id_for_tenant(self.ctx, 'foo_tenant', msg),
            'lb_id'
        )

    def test_get_resource_id_listener_msg(self):
        msg = mock.Mock(
            body={'listener': {'loadbalancer_id': 'lb_id'}}
        )
        lb = self._init_driver()
        self.assertEqual(
            lb.get_resource_id_for_tenant(self.ctx, 'foo_tenant', msg),
            'lb_id'
        )

    def test_get_resource_id_pool_msg(self):
        msg = mock.Mock(
            body={'pool': {'listener_id': 'fake_listener_id'}}
        )
        fake_lb = fakes.fake_loadbalancer()
        self.ctx.neutron.get_loadbalancer_by_listener.return_value = fake_lb
        lb = self._init_driver()
        self.assertEqual(
            lb.get_resource_id_for_tenant(self.ctx, 'foo_tenant', msg),
            fake_lb.id
        )
        self.ctx.neutron.get_loadbalancer_by_listener.assert_called_with(
            'fake_listener_id', 'foo_tenant'
        )

    def test_get_resource_id_member_msg(self):
        msg = mock.Mock(
            body={'member': {'id': 'fake_member_id'}}
        )
        fake_lb = fakes.fake_loadbalancer()
        self.ctx.neutron.get_loadbalancer_by_member.return_value = fake_lb
        lb = self._init_driver()
        self.assertEqual(
            lb.get_resource_id_for_tenant(self.ctx, 'foo_tenant', msg),
            fake_lb.id
        )
        self.ctx.neutron.get_loadbalancer_by_member.assert_called_with(
            'fake_member_id', 'foo_tenant'
        )

    def _test_notification(self, event_type, payload, expected):
        tenant_id = 'fake_tenant_id'
        res = loadbalancer.LoadBalancer.process_notification(
            tenant_id, event_type, payload)
        self.assertEqual(res, expected)

    def test_process_notification_loadbalancerstatus(self):
        self._test_notification('loadbalancerstatus.update', {}, None)

    def test_process_notification_lb_create(self):
        payload = {'loadbalancer': {'id': 'fake_lb_id'}}
        r = event.Resource(
            driver=loadbalancer.LoadBalancer.RESOURCE_NAME,
            id='fake_lb_id',
            tenant_id='fake_tenant_id')
        e = event.Event(
            resource=r,
            crud=event.CREATE,
            body=payload,
        )
        self._test_notification('loadbalancer.create.end', payload, e)

    def test_process_notification_lb_delete(self):
        payload = {'loadbalancer': {'id': 'fake_lb_id'}}
        r = event.Resource(
            driver=loadbalancer.LoadBalancer.RESOURCE_NAME,
            id='fake_lb_id',
            tenant_id='fake_tenant_id')
        e = event.Event(
            resource=r,
            crud=event.DELETE,
            body=payload,
        )
        self._test_notification('loadbalancer.delete.end', payload, e)

    def test_process_notification_lb_update(self):
        payload_formats = [
            {'loadbalancer': {'id': 'fake_lb_id'}},
            {'loadbalancer_id': 'fake_lb_id'},
            {'listener': {'loadbalancer_id': 'fake_lb_id'}},
        ]
        update_notifications = [
            'listener.create.start',
            'pool.create.start',
            'member.create.end',
            'member.delete.end',
        ]
        for notification in update_notifications:
            for payload in payload_formats:
                r = event.Resource(
                    driver=loadbalancer.LoadBalancer.RESOURCE_NAME,
                    id='fake_lb_id',
                    tenant_id='fake_tenant_id')
                e = event.Event(
                    resource=r,
                    crud=event.UPDATE,
                    body=payload,
                )
                self._test_notification(notification, payload, e)

    def test_process_notification_not_subscribed(self):
        self._test_notification('whocares.about.this', {}, None)

    @mock.patch('astara.drivers.loadbalancer.LoadBalancer._ensure_cache')
    def test_get_state_no_lb(self, mock_ensure_cache):
        lb = self._init_driver()
        lb._loadbalancer = None
        self.assertEqual(
            lb.get_state(self.ctx),
            states.GONE,
        )
        mock_ensure_cache.assert_called_with(self.ctx)

    @mock.patch('astara.drivers.loadbalancer.LoadBalancer._ensure_cache')
    def test_get_state(self, mock_ensure_cache):
        lb = self._init_driver()
        fake_lb = fakes.fake_loadbalancer()
        lb._loadbalancer = fake_lb
        self.assertEqual(
            lb.get_state(self.ctx),
            fake_lb.status,
        )
        mock_ensure_cache.assert_called_with(self.ctx)

    @mock.patch('astara.drivers.loadbalancer.LoadBalancer._ensure_cache')
    def test_synchronize_state_no_loadbalancer(self, mock_ensure_cache):
        lb = self._init_driver()
        lb._loadbalancer = None
        lb.synchronize_state(self.ctx, states.DOWN)
        mock_ensure_cache.assert_called_with(self.ctx)
        self.assertFalse(self.ctx.neutron.update_loadbalancer_status.called)

    @mock.patch('astara.drivers.loadbalancer.LoadBalancer._ensure_cache')
    def test_synchronize_state(self, mock_ensure_cache):
        lb = self._init_driver()
        fake_lb = fakes.fake_loadbalancer()
        lb._loadbalancer = fake_lb
        lb.synchronize_state(self.ctx, states.CONFIGURED)
        mock_ensure_cache.assert_called_with(self.ctx)
        self.ctx.neutron.update_loadbalancer_status.assert_called_with(
            lb.id,
            'ACTIVE',
        )
        self.assertEqual(lb._last_synced_status, 'ACTIVE')

    @mock.patch('astara.api.astara_client.get_interfaces')
    def test_get_interfaces(self, mock_get_interfaces):
        mock_get_interfaces.return_value = ['fake_interface']
        lb = self._init_driver()
        self.assertEqual(
            lb.get_interfaces('fake_mgt_addr'), ['fake_interface'])
        mock_get_interfaces.assert_called_with(
            'fake_mgt_addr', self.mgt_port)

    @mock.patch('astara.api.astara_client.is_alive')
    def test_is_alive(self, mock_is_alive):
        mock_is_alive.return_value = False
        lb = self._init_driver()
        self.assertFalse(lb.is_alive('fake_mgt_addr'))
        mock_is_alive.assert_called_with(
            'fake_mgt_addr', self.mgt_port)

    def test__ensure_cache(self):
        lb = self._init_driver()
        self.ctx.neutron.get_loadbalancer_detail.return_value = 'fake_lb'
        lb._ensure_cache(self.ctx)
        self.assertEqual(lb._loadbalancer, 'fake_lb')
        self.ctx.neutron.get_loadbalancer_detail.assert_called_with(lb.id)

    def test__ensure_cache_not_found(self):
        lb = self._init_driver()
        self.ctx.neutron.get_loadbalancer_detail.side_effect = [
            neutron.LoadBalancerGone
        ]
        lb._ensure_cache(self.ctx)
        self.assertIsNone(lb._loadbalancer)
        self.ctx.neutron.get_loadbalancer_detail.assert_called_with(lb.id)
