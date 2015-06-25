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

import logging

import mock
import unittest2 as unittest
from datetime import datetime, timedelta

from akanda.rug import instance_manager
from akanda.rug.api import neutron, nova

instance_manager.RETRY_DELAY = 0.4
instance_manager.BOOT_WAIT = 1

LOG = logging.getLogger(__name__)


class FakeModel(object):
    def __init__(self, id_, **kwargs):
        self.id = id_
        self.__dict__.update(kwargs)


fake_mgt_port = FakeModel(
    '1',
    mac_address='aa:bb:cc:dd:ee:ff',
    network_id='mgt-net',
    fixed_ips=[FakeModel('', ip_address='9.9.9.9', subnet_id='s2')])

fake_int_port = FakeModel(
    '2',
    mac_address='bb:cc:cc:dd:ee:ff',
    network_id='int-net',
    fixed_ips=[FakeModel('', ip_address='10.10.10.10', subnet_id='s3')])

fake_ext_port = FakeModel(
    '3',
    mac_address='cc:cc:cc:dd:ee:ff',
    network_id='ext-net',
    fixed_ips=[FakeModel('', ip_address='192.168.1.1', subnet_id='s4')])

fake_add_port = FakeModel(
    '4',
    mac_address='aa:bb:cc:dd:ff:ff',
    network_id='additional-net',
    fixed_ips=[FakeModel('', ip_address='8.8.8.8', subnet_id='s3')])


class TestInstanceManager(unittest.TestCase):

    def setUp(self):
        self.ctx = mock.Mock()
        self.neutron = self.ctx.neutron
        self.conf = mock.patch.object(instance_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.addCleanup(mock.patch.stopall)

        self.log = mock.Mock()
        self.update_state_p = mock.patch.object(
            instance_manager.InstanceManager,
            'update_state'
        )

        self.INSTANCE_INFO = nova.InstanceInfo(
            instance_id='fake_instance_id',
            name='fake_name',
            image_uuid='fake_image_id',
            booting=False,
            last_boot=(datetime.utcnow() - timedelta(minutes=15)),
            ports=[fake_int_port, fake_ext_port, fake_mgt_port],
            management_port=fake_mgt_port,
        )

        self.mock_update_state = self.update_state_p.start()
        self.instance_mgr = instance_manager.InstanceManager('the_id',
                                                             'tenant_id',
                                                             self.log,
                                                             self.ctx)
        self.instance_mgr.instance_info = self.INSTANCE_INFO
        mock.patch.object(self.instance_mgr, '_ensure_cache', mock.Mock)

        self.next_state = None

        def next_state(*args, **kwargs):
            if self.next_state:
                self.instance_mgr.state = self.next_state
            return self.instance_mgr.state
        self.mock_update_state.side_effect = next_state

    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_update_state_is_alive(self, router_api):
        self.update_state_p.stop()
        router_api.is_alive.return_value = True

        self.assertEqual(self.instance_mgr.update_state(self.ctx),
                         instance_manager.UP)
        router_api.is_alive.assert_called_once_with(
            self.INSTANCE_INFO.management_address,
            self.conf.akanda_mgt_service_port)

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.instance_manager.router_api')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_router_status_sync(self, config, router_api):
        self.update_state_p.stop()
        router_api.is_alive.return_value = False
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        rtr.management_port = mock.Mock()
        rtr.external_port = mock.Mock()
        self.ctx.neutron.get_router_detail.return_value = rtr
        n = self.neutron

        # Router state should start down
        self.instance_mgr.update_state(self.ctx)
        n.update_router_status.assert_called_once_with('R1', 'DOWN')
        n.update_router_status.reset_mock()

        # Bring the router to UP with `is_alive = True`
        router_api.is_alive.return_value = True
        self.instance_mgr.update_state(self.ctx)
        n.update_router_status.assert_called_once_with('R1', 'BUILD')
        n.update_router_status.reset_mock()

        # Configure the router and make sure state is synchronized as ACTIVE
        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = True
            self.instance_mgr.last_boot = datetime.utcnow()
            self.instance_mgr.configure(self.ctx)
            self.instance_mgr.update_state(self.ctx)
            n.update_router_status.assert_called_once_with('R1', 'ACTIVE')
            n.update_router_status.reset_mock()

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.instance_manager.router_api')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_router_status_caching(self, config, router_api):
        self.update_state_p.stop()
        router_api.is_alive.return_value = False
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        rtr.management_port = mock.Mock()
        rtr.external_port = mock.Mock()
        self.ctx.neutron.get_router_detail.return_value = rtr
        n = self.neutron

        # Router state should start down
        self.instance_mgr.update_state(self.ctx)
        n.update_router_status.assert_called_once_with('R1', 'DOWN')
        n.update_router_status.reset_mock()

        # Router state should not be updated in neutron if it didn't change
        self.instance_mgr.update_state(self.ctx)
        self.assertEqual(n.update_router_status.call_count, 0)

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_boot_timeout_still_booting(self, router_api, sleep):
        now = datetime.utcnow()
        self.INSTANCE_INFO.last_boot = now
        self.instance_mgr.last_boot = now
        self.update_state_p.stop()
        router_api.is_alive.return_value = False

        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            instance_manager.BOOTING
        )
        router_api.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
        ])

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_boot_timeout_error(self, router_api, sleep):
        self.instance_mgr.state = instance_manager.ERROR
        self.instance_mgr.last_boot = datetime.utcnow()
        self.update_state_p.stop()
        router_api.is_alive.return_value = False

        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            instance_manager.ERROR,
        )
        router_api.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
        ])

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_boot_timeout_error_no_last_boot(self, router_api, sleep):
        self.instance_mgr.state = instance_manager.ERROR
        self.instance_mgr.last_boot = None
        self.update_state_p.stop()
        router_api.is_alive.return_value = False

        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            instance_manager.ERROR,
        )
        router_api.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
        ])

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_boot_timeout(self, router_api, sleep):
        self.instance_mgr.last_boot = datetime.utcnow() - timedelta(minutes=5)
        self.update_state_p.stop()
        router_api.is_alive.return_value = False

        self.assertEqual(self.instance_mgr.update_state(self.ctx),
                         instance_manager.DOWN)
        router_api.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
        ])
        self.instance_mgr.log.info.assert_called_once_with(
            mock.ANY,
            self.conf.boot_timeout
        )

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_update_state_is_down(self, router_api, sleep):
        self.update_state_p.stop()
        router_api.is_alive.return_value = False

        self.assertEqual(self.instance_mgr.update_state(self.ctx),
                         instance_manager.DOWN)
        router_api.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
        ])

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_update_state_retry_delay(self, router_api, sleep):
        self.update_state_p.stop()
        router_api.is_alive.side_effect = [False, False, True]
        max_retries = 5
        self.conf.max_retries = max_retries
        self.instance_mgr.update_state(self.ctx, silent=False)
        self.assertEqual(sleep.call_count, 2)
        self.log.debug.assert_has_calls([
            mock.call('Alive check failed. Attempt %d of %d', 0, max_retries),
            mock.call('Alive check failed. Attempt %d of %d', 1, max_retries)
        ])

    @mock.patch('time.sleep')
    def test_boot_success(self, sleep):
        self.next_state = instance_manager.UP
        rtr = mock.sentinel.router
        self.ctx.neutron.get_router_detail.return_value = rtr
        rtr.id = 'ROUTER1'
        rtr.management_port = None
        rtr.external_port = None
        rtr.ports = mock.MagicMock()
        rtr.ports.__iter__.return_value = []
        self.instance_mgr.boot(self.ctx, 'GLANCE-IMAGE-123')
        self.assertEqual(self.instance_mgr.state, instance_manager.BOOTING)
        self.ctx.nova_client.boot_instance.assert_called_once_with(
            self.INSTANCE_INFO, rtr.id, 'GLANCE-IMAGE-123', mock.ANY)
        self.assertEqual(1, self.instance_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_fail(self, sleep):
        self.next_state = instance_manager.DOWN
        rtr = mock.sentinel.router
        self.ctx.neutron.get_router_detail.return_value = rtr
        rtr.id = 'ROUTER1'
        rtr.management_port = None
        rtr.external_port = None
        rtr.ports = mock.MagicMock()
        rtr.ports.__iter__.return_value = []
        self.instance_mgr.boot(self.ctx, 'GLANCE-IMAGE-123')
        self.assertEqual(self.instance_mgr.state, instance_manager.BOOTING)
        self.ctx.nova_client.boot_instance.assert_called_once_with(
            self.INSTANCE_INFO, rtr.id, 'GLANCE-IMAGE-123', mock.ANY)
        self.assertEqual(1, self.instance_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_exception(self, sleep):
        rtr = mock.sentinel.router
        self.ctx.neutron.get_router_detail.return_value = rtr
        rtr.id = 'ROUTER1'
        rtr.management_port = None
        rtr.external_port = None
        rtr.ports = mock.MagicMock()
        rtr.ports.__iter__.return_value = []

        self.ctx.nova_client.boot_instance.side_effect = RuntimeError
        self.instance_mgr.boot(self.ctx, 'GLANCE-IMAGE-123')
        self.assertEqual(self.instance_mgr.state, instance_manager.DOWN)
        self.ctx.nova_client.boot_instance.assert_called_once_with(
            self.INSTANCE_INFO, rtr.id, 'GLANCE-IMAGE-123', mock.ANY)
        self.assertEqual(1, self.instance_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_with_port_cleanup(self, sleep):
        self.next_state = instance_manager.UP

        management_port = mock.Mock(id='mgmt', device_id='INSTANCE1')
        external_port = mock.Mock(id='ext', device_id='INSTANCE1')
        internal_port = mock.Mock(id='int', device_id='INSTANCE1')

        rtr = mock.sentinel.router
        instance = mock.sentinel.instance
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.ctx.nova_client.get_instance.return_value = instance
        rtr.id = 'ROUTER1'
        instance.id = 'INSTANCE1'
        rtr.management_port = management_port
        rtr.external_port = external_port
        rtr.ports = mock.MagicMock()
        rtr.ports.__iter__.return_value = [management_port, external_port,
                                           internal_port]
        self.instance_mgr.boot(self.ctx, 'GLANCE-IMAGE-123')
        self.assertEqual(self.instance_mgr.state, instance_manager.BOOTING)
        self.ctx.nova_client.boot_instance.assert_called_once_with(
            self.INSTANCE_INFO,
            rtr.id,
            'GLANCE-IMAGE-123',
            mock.ANY,  # TODO(adam_g): actually test make_vrrp_ports()
        )

    def test_boot_check_up(self):
        with mock.patch.object(
            instance_manager.InstanceManager,
            'update_state'
        ) as update_state:
            with mock.patch.object(
                instance_manager.InstanceManager,
                'configure'
            ) as configure:
                update_state.return_value = instance_manager.UP
                configure.side_effect = lambda *a, **kw: setattr(
                    self.instance_mgr,
                    'state',
                    instance_manager.CONFIGURED
                )
                assert self.instance_mgr.check_boot(self.ctx) is True
                update_state.assert_called_once_with(self.ctx, silent=True)
                configure.assert_called_once_with(
                    self.ctx,
                    instance_manager.BOOTING,
                    attempts=1
                )

    def test_boot_check_configured(self):
        with mock.patch.object(
            instance_manager.InstanceManager,
            'update_state'
        ) as update_state:
            with mock.patch.object(
                instance_manager.InstanceManager,
                'configure'
            ) as configure:
                update_state.return_value = instance_manager.CONFIGURED
                configure.side_effect = lambda *a, **kw: setattr(
                    self.instance_mgr,
                    'state',
                    instance_manager.CONFIGURED
                )
                assert self.instance_mgr.check_boot(self.ctx) is True
                update_state.assert_called_once_with(self.ctx, silent=True)
                configure.assert_called_once_with(
                    self.ctx,
                    instance_manager.BOOTING,
                    attempts=1
                )

    def test_boot_check_still_booting(self):
        with mock.patch.object(
            instance_manager.InstanceManager,
            'update_state'
        ) as update_state:
            update_state.return_value = instance_manager.BOOTING
            assert self.instance_mgr.check_boot(self.ctx) is False
            update_state.assert_called_once_with(self.ctx, silent=True)

    def test_boot_check_unsuccessful_initial_config_update(self):
        with mock.patch.object(
            instance_manager.InstanceManager,
            'update_state'
        ) as update_state:
            with mock.patch.object(
                instance_manager.InstanceManager,
                'configure'
            ) as configure:
                update_state.return_value = instance_manager.CONFIGURED
                configure.side_effect = lambda *a, **kw: setattr(
                    self.instance_mgr,
                    'state',
                    instance_manager.BOOTING
                )
                assert self.instance_mgr.check_boot(self.ctx) is False
                update_state.assert_called_once_with(self.ctx, silent=True)
                configure.assert_called_once_with(
                    self.ctx,
                    instance_manager.BOOTING,
                    attempts=1
                )

    @mock.patch('time.sleep')
    def test_stop_success(self, sleep):
        self.instance_mgr.state = instance_manager.UP
        self.ctx.nova_client.get_instance_by_id.return_value = None
        self.instance_mgr.stop(self.ctx)
        self.ctx.nova_client.destroy_instance.assert_called_once_with(
            self.INSTANCE_INFO
        )
        self.assertEqual(self.instance_mgr.state, instance_manager.DOWN)

    @mock.patch('time.sleep')
    def test_stop_fail(self, sleep):
        self.instance_mgr.state = instance_manager.UP
        self.ctx.nova_client.get_router_instance_status.return_value = 'UP'
        self.instance_mgr.stop(self.ctx)
        self.assertEqual(self.instance_mgr.state, instance_manager.UP)
        self.ctx.nova_client.destroy_instance.assert_called_once_with(
            self.INSTANCE_INFO
        )
        self.log.error.assert_called_once_with(mock.ANY, 1)

    @mock.patch('time.sleep')
    def test_stop_router_already_deleted_from_neutron(self, sleep):
        self.instance_mgr.state = instance_manager.GONE
        self.instance_mgr.stop(self.ctx)
        self.ctx.nova_client.destroy_instance.assert_called_once_with(
            self.INSTANCE_INFO)
        self.assertEqual(self.instance_mgr.state, instance_manager.GONE)

    @mock.patch('akanda.rug.instance_manager.router_api')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_configure_success(self, config, router_api):
        rtr = mock.sentinel.router

        self.ctx.neutron.get_router_detail.return_value = rtr
        config.return_value = 'fake_config'
        router_api.get_interfaces.return_value = []

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = True
            self.instance_mgr.configure(self.ctx)

            verify.assert_called_once_with(rtr, [])
            config.assert_called_once_with(
                self.ctx.neutron, rtr, fake_mgt_port, {})
            router_api.update_config.assert_called_once_with(
                self.INSTANCE_INFO.management_address, 5000, 'fake_config',
            )
            self.assertEqual(self.instance_mgr.state,
                             instance_manager.CONFIGURED)

    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_configure_mismatched_interfaces(self, router_api):
        rtr = mock.sentinel.router

        self.neutron.get_router_detail.return_value = rtr

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = False
            self.instance_mgr.configure(self.ctx)

            interfaces = router_api.get_interfaces.return_value

            verify.assert_called_once_with(rtr, interfaces)

            self.assertFalse(router_api.update_config.called)
            self.assertEqual(self.instance_mgr.state, instance_manager.REPLUG)

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.instance_manager.router_api')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_configure_failure(self, config, router_api, sleep):
        rtr = {'id': 'the_id'}

        self.neutron.get_router_detail.return_value = rtr

        router_api.update_config.side_effect = Exception
        config.return_value = 'fake_config'

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = True
            self.instance_mgr.configure(self.ctx)

            interfaces = router_api.get_interfaces.return_value
            verify.assert_called_once_with(rtr, interfaces)

            config.assert_called_once_with(
                self.neutron, rtr, fake_mgt_port, {})
            expected_calls = [
                mock.call(self.INSTANCE_INFO.management_address, 5000,
                          'fake_config')
                for i in range(0, 2)]
            router_api.update_config.assert_has_calls(expected_calls)
            self.assertEqual(self.instance_mgr.state, instance_manager.RESTART)

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_replug_add_new_port_success(self, router_api):
        self.instance_mgr.state = instance_manager.REPLUG

        fake_router = mock.Mock()
        fake_router.id = 'fake_router_id'
        fake_router.ports = [fake_ext_port, fake_int_port, fake_add_port]

        self.neutron.get_router_detail.return_value = fake_router
        self.instance_mgr.router_obj = fake_router
        router_api.get_interfaces.return_value = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
            {'lladdr': fake_int_port.mac_address}
        ]
        self.conf.hotplug_timeout = 5

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)
        fake_new_port = mock.Mock(id='fake_new_port_id')
        self.ctx.neutron.create_vrrp_port.return_value = fake_new_port

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = True  # the hotplug worked!
            self.instance_mgr.replug(self.ctx)

            self.ctx.neutron.create_vrrp_port.assert_called_with(
                fake_router.id, 'additional-net'
            )
            self.assertEqual(self.instance_mgr.state, instance_manager.REPLUG)
            fake_instance.interface_attach.assert_called_once_with(
                fake_new_port.id, None, None
            )
            self.assertIn(fake_new_port, self.INSTANCE_INFO.ports)

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_replug_add_new_port_failure(self, router_api):
        self.instance_mgr.state = instance_manager.REPLUG

        fake_router = mock.Mock()
        fake_router.id = 'fake_router_id'
        fake_router.ports = [fake_ext_port, fake_int_port, fake_add_port]

        self.neutron.get_router_detail.return_value = fake_router
        self.instance_mgr.router_obj = fake_router
        router_api.get_interfaces.return_value = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
            {'lladdr': fake_int_port.mac_address}
        ]
        self.conf.hotplug_timeout = 5

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)

        fake_new_port = mock.Mock(id='fake_new_port_id')
        self.ctx.neutron.create_vrrp_port.return_value = fake_new_port

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = False  # The hotplug didn't work!
            self.instance_mgr.replug(self.ctx)
            self.assertEqual(self.instance_mgr.state, instance_manager.RESTART)

            fake_instance.interface_attach.assert_called_once_with(
                fake_new_port.id, None, None
            )

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_replug_remove_port_success(self, router_api):
        self.instance_mgr.state = instance_manager.REPLUG

        fake_router = mock.Mock()
        fake_router.id = 'fake_router_id'

        # Router lacks the fake_ext_port, it will be unplugged
        fake_router.ports = [fake_mgt_port, fake_int_port]

        self.neutron.get_router_detail.return_value = fake_router
        self.instance_mgr.router_obj = fake_router
        router_api.get_interfaces.return_value = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
            {'lladdr': fake_int_port.mac_address}
        ]
        self.conf.hotplug_timeout = 5

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = True  # the unplug worked!
            self.instance_mgr.replug(self.ctx)
            self.assertEqual(self.instance_mgr.state, instance_manager.REPLUG)
            fake_instance.interface_detach.assert_called_once_with(
                fake_ext_port.id
            )
            self.assertNotIn(fake_ext_port, self.INSTANCE_INFO.ports)

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.instance_manager.router_api')
    def test_replug_remove_port_failure(self, router_api):
        self.instance_mgr.state = instance_manager.REPLUG

        fake_router = mock.Mock()
        fake_router.id = 'fake_router_id'

        # Router lacks the fake_ext_port, it will be unplugged
        fake_router.ports = [fake_mgt_port, fake_int_port]

        self.neutron.get_router_detail.return_value = fake_router
        self.instance_mgr.router_obj = fake_router
        router_api.get_interfaces.return_value = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
            {'lladdr': fake_int_port.mac_address}
        ]
        self.conf.hotplug_timeout = 5

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = False  # the unplug failed!
            self.instance_mgr.replug(self.ctx)
            self.assertEquals(self.instance_mgr.state,
                              instance_manager.RESTART)
            fake_instance.interface_detach.assert_called_once_with(
                fake_ext_port.id
            )

    def test_verify_interfaces(self):
        rtr = mock.Mock()
        rtr.management_port.mac_address = fake_mgt_port.mac_address
        rtr.external_port.mac_address = fake_ext_port.mac_address
        p = mock.Mock()
        p.mac_address = fake_int_port.mac_address
        rtr.internal_ports = [p]
        rtr.ports = [p, rtr.management_port, rtr.external_port]

        interfaces = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
            {'lladdr': fake_int_port.mac_address}
        ]

        self.assertTrue(self.instance_mgr._verify_interfaces(rtr, interfaces))

    def test_verify_interfaces_with_cleared_gateway(self):
        rtr = mock.Mock()
        rtr.management_port = mock.MagicMock(spec=[])
        rtr.external_port.mac_address = 'd:c:b:a'
        p = mock.Mock()
        p.mac_address = 'a:a:a:a'
        rtr.internal_ports = [p]
        rtr.ports = [p, rtr.management_port, rtr.external_port]

        interfaces = [
            {'lladdr': 'a:b:c:d'},
            {'lladdr': 'd:c:b:a'},
            {'lladdr': 'a:a:a:a'}
        ]

        self.assertFalse(self.instance_mgr._verify_interfaces(rtr, interfaces))

    def test_ensure_provider_ports(self):
        rtr = mock.Mock()
        rtr.external_port = None
        self.assertEqual(self.instance_mgr._ensure_provider_ports(rtr,
                                                                  self.ctx),
                         rtr)
        self.neutron.create_router_external_port.assert_called_once_with(rtr)

    def test_set_error_when_gone(self):
        self.instance_mgr.state = instance_manager.GONE
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.instance_mgr.set_error(self.ctx)
        self.neutron.update_router_status.assert_called_once_with('R1',
                                                                  'ERROR')
        self.assertEqual(instance_manager.GONE, self.instance_mgr.state)

    def test_set_error_when_booting(self):
        self.instance_mgr.state = instance_manager.BOOTING
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.instance_mgr.set_error(self.ctx)
        self.neutron.update_router_status.assert_called_once_with('R1',
                                                                  'ERROR')
        self.assertEqual(instance_manager.ERROR, self.instance_mgr.state)

    def test_clear_error_when_gone(self):
        self.instance_mgr.state = instance_manager.GONE
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.instance_mgr.clear_error(self.ctx)
        self.neutron.update_router_status.assert_called_once_with('R1',
                                                                  'ERROR')
        self.assertEqual(instance_manager.GONE, self.instance_mgr.state)

    def test_set_error_when_error(self):
        self.instance_mgr.state = instance_manager.ERROR
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.instance_mgr.clear_error(self.ctx)
        self.neutron.update_router_status.assert_called_once_with('R1',
                                                                  'DOWN')
        self.assertEqual(instance_manager.DOWN, self.instance_mgr.state)

    @mock.patch('time.sleep')
    def test_boot_success_after_error(self, sleep):
        self.next_state = instance_manager.UP
        rtr = mock.sentinel.router
        self.ctx.neutron.get_router_detail.return_value = rtr
        rtr.id = 'ROUTER1'
        rtr.management_port = None
        rtr.external_port = None
        rtr.ports = mock.MagicMock()
        rtr.ports.__iter__.return_value = []
        self.instance_mgr.set_error(self.ctx)
        self.instance_mgr.boot(self.ctx, 'GLANCE-IMAGE-123')
        self.assertEqual(self.instance_mgr.state, instance_manager.BOOTING)
        self.ctx.nova_client.boot_instance.assert_called_once_with(
            self.INSTANCE_INFO, rtr.id, 'GLANCE-IMAGE-123', mock.ANY)

    def test_error_cooldown(self):
        self.conf.error_state_cooldown = 30
        self.assertIsNone(self.instance_mgr.last_error)
        self.assertFalse(self.instance_mgr.error_cooldown)

        self.instance_mgr.state = instance_manager.ERROR
        self.instance_mgr.last_error = datetime.utcnow() - timedelta(seconds=1)
        self.assertTrue(self.instance_mgr.error_cooldown)

        self.instance_mgr.last_error = datetime.utcnow() - timedelta(minutes=5)
        self.assertFalse(self.instance_mgr.error_cooldown)


class TestBootAttemptCounter(unittest.TestCase):

    def setUp(self):
        self.c = instance_manager.BootAttemptCounter()

    def test_start(self):
        self.c.start()
        self.assertEqual(1, self.c._attempts)
        self.c.start()
        self.assertEqual(2, self.c._attempts)

    def test_reset(self):
        self.c._attempts = 2
        self.c.reset()
        self.assertEqual(0, self.c._attempts)


class TestSynchronizeRouterStatus(unittest.TestCase):

    def setUp(self):
        self.test_instance_manager = mock.Mock(spec=('router_obj',
                                                     '_last_synced_status',
                                                     'state'))
        self.test_context = mock.Mock()

    def test_router_is_deleted(self):
        self.test_instance_manager.router_obj = None
        v = instance_manager.synchronize_router_status(
            lambda instance_manager_inst, ctx, silent: 1)
        self.assertEqual(v(self.test_instance_manager, {}), 1)

    def test_router_status_changed(self):
        self.test_instance_manager.router_obj = mock.Mock(id='ABC123')
        self.test_instance_manager._last_synced_status = neutron.STATUS_ACTIVE
        self.test_instance_manager.state = instance_manager.DOWN
        v = instance_manager.synchronize_router_status(
            lambda instance_manager_inst, ctx, silent: 1)
        self.assertEqual(v(self.test_instance_manager, self.test_context), 1)
        self.test_context.neutron.update_router_status.\
            assert_called_once_with(
                'ABC123',
                neutron.STATUS_DOWN)
        self.assertEqual(self.test_instance_manager._last_synced_status,
                         neutron.STATUS_DOWN)

    def test_router_status_same(self):
        self.test_instance_manager.router_obj = mock.Mock(id='ABC123')
        self.test_instance_manager._last_synced_status = neutron.STATUS_ACTIVE
        self.test_instance_manager.state = instance_manager.CONFIGURED
        v = instance_manager.synchronize_router_status(
            lambda instance_manager_inst, ctx, silent: 1)
        self.assertEqual(v(self.test_instance_manager, self.test_context), 1)
        self.assertEqual(
            self.test_context.neutron.update_router_status.call_count, 0)
        self.assertEqual(self.test_instance_manager._last_synced_status,
                         neutron.STATUS_ACTIVE)
