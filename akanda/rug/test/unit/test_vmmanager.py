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

from akanda.rug import vm_manager

vm_manager.RETRY_DELAY = 0.4
vm_manager.BOOT_WAIT = 1

LOG = logging.getLogger(__name__)


class TestVmManager(unittest.TestCase):

    def setUp(self):
        self.ctx = mock.Mock()
        self.quantum = self.ctx.neutron
        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.conf.max_retries = 3
        self.addCleanup(mock.patch.stopall)

        self.log = mock.Mock()
        self.update_state_p = mock.patch.object(
            vm_manager.VmManager,
            'update_state'
        )

        self.mock_update_state = self.update_state_p.start()
        self.vm_mgr = vm_manager.VmManager('the_id', 'tenant_id',
                                           self.log, self.ctx)
        mock.patch.object(self.vm_mgr, '_ensure_cache', mock.Mock)

        self.next_state = None

        def next_state(*args, **kwargs):
            if self.next_state:
                self.vm_mgr.state = self.next_state
            return self.vm_mgr.state
        self.mock_update_state.side_effect = next_state

    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_update_state_is_alive(self, get_mgt_addr, router_api):
        self.update_state_p.stop()
        get_mgt_addr.return_value = 'fe80::beef'
        router_api.is_alive.return_value = True

        self.assertEqual(self.vm_mgr.update_state(self.ctx), vm_manager.UP)
        router_api.is_alive.assert_called_once_with('fe80::beef', 5000)

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_router_status_sync(self, config, get_mgt_addr, router_api):
        self.update_state_p.stop()
        router_api.is_alive.return_value = False
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        rtr.management_port = mock.Mock()
        rtr.external_port = mock.Mock()
        self.ctx.neutron.get_router_detail.return_value = rtr
        n = self.quantum

        # Router state should start down
        self.vm_mgr.update_state(self.ctx)
        n.update_router_status.assert_called_once_with('R1', 'DOWN')
        n.update_router_status.reset_mock()

        # Bring the router to UP with `is_alive = True`
        router_api.is_alive.return_value = True
        self.vm_mgr.update_state(self.ctx)
        n.update_router_status.assert_called_once_with('R1', 'BUILD')
        n.update_router_status.reset_mock()

        # Configure the router and make sure state is synchronized as ACTIVE
        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = True
            self.vm_mgr.last_boot = datetime.utcnow()
            self.vm_mgr.configure(self.ctx)
            self.vm_mgr.update_state(self.ctx)
            n.update_router_status.assert_called_once_with('R1', 'ACTIVE')
            n.update_router_status.reset_mock()

        # Removing the management port will trigger a reboot
        rtr.management_port = None
        self.vm_mgr.update_state(self.ctx)
        n.update_router_status.assert_called_once_with('R1', 'DOWN')
        n.update_router_status.reset_mock()

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_boot_timeout_still_booting(self, get_mgt_addr, router_api, sleep):
        self.vm_mgr.last_boot = datetime.utcnow()
        self.update_state_p.stop()
        get_mgt_addr.return_value = 'fe80::beef'
        router_api.is_alive.return_value = False

        self.assertEqual(
            self.vm_mgr.update_state(self.ctx),
            vm_manager.BOOTING
        )
        router_api.is_alive.assert_has_calls([
            mock.call('fe80::beef', 5000),
            mock.call('fe80::beef', 5000),
            mock.call('fe80::beef', 5000)
        ])

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_boot_timeout(self, get_mgt_addr, router_api, sleep):
        self.vm_mgr.last_boot = datetime.utcnow() - timedelta(minutes=5)
        self.update_state_p.stop()
        get_mgt_addr.return_value = 'fe80::beef'
        router_api.is_alive.return_value = False

        self.assertEqual(self.vm_mgr.update_state(self.ctx), vm_manager.DOWN)
        router_api.is_alive.assert_has_calls([
            mock.call('fe80::beef', 5000),
            mock.call('fe80::beef', 5000),
            mock.call('fe80::beef', 5000)
        ])
        self.vm_mgr.log.info.assert_called_once_with(
            mock.ANY,
            self.conf.boot_timeout
        )

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_update_state_is_down(self, get_mgt_addr, router_api, sleep):
        self.update_state_p.stop()
        get_mgt_addr.return_value = 'fe80::beef'
        router_api.is_alive.return_value = False

        self.assertEqual(self.vm_mgr.update_state(self.ctx), vm_manager.DOWN)
        router_api.is_alive.assert_has_calls([
            mock.call('fe80::beef', 5000),
            mock.call('fe80::beef', 5000),
            mock.call('fe80::beef', 5000)
        ])

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_update_state_retry_delay(self, get_mgt_addr, router_api, sleep):
        self.update_state_p.stop()
        get_mgt_addr.return_value = 'fe80::beef'
        router_api.is_alive.side_effect = [False, False, True]
        max_retries = 5
        self.conf.max_retries = max_retries
        self.vm_mgr.update_state(self.ctx, silent=False)
        self.assertEqual(sleep.call_count, 2)
        self.log.debug.assert_has_calls([
            mock.call('Alive check failed. Attempt %d of %d', 0, max_retries),
            mock.call('Alive check failed. Attempt %d of %d', 1, max_retries)
        ])

    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_update_state_no_mgt_port(self, get_mgt_addr):
        with mock.patch.object(self.ctx.neutron, 'get_router_detail') as grd:
            r = mock.Mock()
            r.management_port = None
            grd.return_value = r
            get_mgt_addr.side_effect = AssertionError('Should never be called')
            self.update_state_p.stop()
            self.assertEqual(self.vm_mgr.update_state(self.ctx),
                             vm_manager.DOWN)

    @mock.patch('time.sleep')
    def test_boot_success(self, sleep):
        self.next_state = vm_manager.UP
        rtr = mock.sentinel.router
        self.ctx.neutron.get_router_detail.return_value = rtr
        rtr.id = 'ROUTER1'
        rtr.management_port = None
        rtr.external_port = None
        rtr.ports = mock.MagicMock()
        rtr.ports.__iter__.return_value = []
        self.vm_mgr.boot(self.ctx)
        self.assertEqual(self.vm_mgr.state, vm_manager.DOWN)  # async
        self.ctx.nova_client.reboot_router_instance.assert_called_once_with(
            self.vm_mgr.router_obj
        )
        self.assertEqual(1, self.vm_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_fail(self, sleep):
        self.next_state = vm_manager.DOWN
        rtr = mock.sentinel.router
        self.ctx.neutron.get_router_detail.return_value = rtr
        rtr.id = 'ROUTER1'
        rtr.management_port = None
        rtr.external_port = None
        rtr.ports = mock.MagicMock()
        rtr.ports.__iter__.return_value = []
        self.vm_mgr.boot(self.ctx)
        self.assertEqual(self.vm_mgr.state, vm_manager.DOWN)
        self.ctx.nova_client.reboot_router_instance.assert_called_once_with(
            self.vm_mgr.router_obj
        )
        self.assertEqual(1, self.vm_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_with_port_cleanup(self, sleep):
        self.next_state = vm_manager.UP

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
        self.vm_mgr.boot(self.ctx)
        self.assertEqual(self.vm_mgr.state, vm_manager.DOWN)  # async
        self.ctx.nova_client.reboot_router_instance.assert_called_once_with(
            self.vm_mgr.router_obj
        )
        assert self.ctx.neutron.clear_device_id.call_count == 3
        self.ctx.neutron.clear_device_id.assert_has_calls([
            mock.call(management_port),
            mock.call(external_port),
            mock.call(internal_port)
        ], any_order=True)

    def test_boot_check_up(self):
        with mock.patch.object(
            vm_manager.VmManager,
            'update_state'
        ) as update_state:
            with mock.patch.object(
                vm_manager.VmManager,
                'configure'
            ) as configure:
                update_state.return_value = vm_manager.UP
                configure.side_effect = lambda *a, **kw: setattr(
                    self.vm_mgr,
                    'state',
                    vm_manager.CONFIGURED
                )
                assert self.vm_mgr.check_boot(self.ctx) is True
                update_state.assert_called_once_with(self.ctx, silent=True)
                configure.assert_called_once_with(
                    self.ctx,
                    vm_manager.BOOTING,
                    attempts=1
                )

    def test_boot_check_configured(self):
        with mock.patch.object(
            vm_manager.VmManager,
            'update_state'
        ) as update_state:
            with mock.patch.object(
                vm_manager.VmManager,
                'configure'
            ) as configure:
                update_state.return_value = vm_manager.CONFIGURED
                configure.side_effect = lambda *a, **kw: setattr(
                    self.vm_mgr,
                    'state',
                    vm_manager.CONFIGURED
                )
                assert self.vm_mgr.check_boot(self.ctx) is True
                update_state.assert_called_once_with(self.ctx, silent=True)
                configure.assert_called_once_with(
                    self.ctx,
                    vm_manager.BOOTING,
                    attempts=1
                )

    def test_boot_check_still_booting(self):
        with mock.patch.object(
            vm_manager.VmManager,
            'update_state'
        ) as update_state:
            update_state.return_value = vm_manager.BOOTING
            assert self.vm_mgr.check_boot(self.ctx) is False
            update_state.assert_called_once_with(self.ctx, silent=True)

    def test_boot_check_unsuccessful_initial_config_update(self):
        with mock.patch.object(
            vm_manager.VmManager,
            'update_state'
        ) as update_state:
            with mock.patch.object(
                vm_manager.VmManager,
                'configure'
            ) as configure:
                update_state.return_value = vm_manager.CONFIGURED
                configure.side_effect = lambda *a, **kw: setattr(
                    self.vm_mgr,
                    'state',
                    vm_manager.BOOTING
                )
                assert self.vm_mgr.check_boot(self.ctx) is False
                update_state.assert_called_once_with(self.ctx, silent=True)
                configure.assert_called_once_with(
                    self.ctx,
                    vm_manager.BOOTING,
                    attempts=1
                )

    @mock.patch('time.sleep')
    def test_stop_success(self, sleep):
        self.vm_mgr.state = vm_manager.UP
        self.ctx.nova_client.get_router_instance_status.return_value = None
        self.vm_mgr.stop(self.ctx)
        self.ctx.nova_client.destroy_router_instance.assert_called_once_with(
            self.vm_mgr.router_obj
        )
        self.assertEqual(self.vm_mgr.state, vm_manager.DOWN)

    @mock.patch('time.sleep')
    def test_stop_fail(self, sleep):
        self.vm_mgr.state = vm_manager.UP
        self.ctx.nova_client.get_router_instance_status.return_value = 'UP'
        self.vm_mgr.stop(self.ctx)
        self.assertEqual(self.vm_mgr.state, vm_manager.UP)
        self.ctx.nova_client.destroy_router_instance.assert_called_once_with(
            self.vm_mgr.router_obj
        )
        self.log.error.assert_called_once_with(mock.ANY, 1)

    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_configure_success(self, config, get_mgt_addr, router_api):
        get_mgt_addr.return_value = 'fe80::beef'
        rtr = mock.sentinel.router

        self.ctx.neutron.get_router_detail.return_value = rtr

        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = True
            self.vm_mgr.configure(self.ctx)

            interfaces = router_api.get_interfaces.return_value

            verify.assert_called_once_with(rtr, interfaces)
            config.assert_called_once_with(self.ctx.neutron, rtr, interfaces)
            router_api.update_config.assert_called_once_with(
                'fe80::beef',
                5000,
                config.return_value
            )
            self.assertEqual(self.vm_mgr.state, vm_manager.CONFIGURED)

    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_configure_mismatched_interfaces(self, get_mgt_addr, router_api):
        get_mgt_addr.return_value = 'fe80::beef'
        rtr = mock.sentinel.router

        self.quantum.get_router_detail.return_value = rtr

        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = False
            self.vm_mgr.configure(self.ctx)

            interfaces = router_api.get_interfaces.return_value

            verify.assert_called_once_with(rtr, interfaces)

            self.assertFalse(router_api.update_config.called)
            self.assertEqual(self.vm_mgr.state, vm_manager.RESTART)

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_configure_failure(self, config, get_mgt_addr, router_api, sleep):
        get_mgt_addr.return_value = 'fe80::beef'
        rtr = {'id': 'the_id'}

        self.quantum.get_router_detail.return_value = rtr

        router_api.update_config.side_effect = Exception

        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = True
            self.vm_mgr.configure(self.ctx)

            interfaces = router_api.get_interfaces.return_value

            verify.assert_called_once_with(rtr, interfaces)
            config.assert_called_once_with(self.quantum, rtr, interfaces)
            router_api.update_config.assert_has_calls([
                mock.call('fe80::beef', 5000, config.return_value),
                mock.call('fe80::beef', 5000, config.return_value),
                mock.call('fe80::beef', 5000, config.return_value),
            ])
            self.assertEqual(self.vm_mgr.state, vm_manager.RESTART)

    def test_verify_interfaces(self):
        rtr = mock.Mock()
        rtr.management_port.mac_address = 'a:b:c:d'
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

        self.assertTrue(self.vm_mgr._verify_interfaces(rtr, interfaces))

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

        self.assertFalse(self.vm_mgr._verify_interfaces(rtr, interfaces))

    def test_ensure_provider_ports(self):
        rtr = mock.Mock()
        rtr.id = 'id'
        rtr.management_port = None
        rtr.external_port = None

        self.vm_mgr._ensure_provider_ports(rtr, self.ctx)
        self.quantum.create_router_management_port.assert_called_once_with(
            'id'
        )

        self.assertEqual(self.vm_mgr._ensure_provider_ports(rtr, self.ctx),
                         rtr)
        self.quantum.create_router_external_port.assert_called_once_with(rtr)

    def test_set_error_when_gone(self):
        self.vm_mgr.state = vm_manager.GONE
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.set_error(self.ctx)
        self.quantum.update_router_status.assert_called_once_with('R1',
                                                                  'ERROR')
        self.assertEqual(vm_manager.GONE, self.vm_mgr.state)

    def test_set_error_when_booting(self):
        self.vm_mgr.state = vm_manager.BOOTING
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.set_error(self.ctx)
        self.quantum.update_router_status.assert_called_once_with('R1',
                                                                  'ERROR')
        self.assertEqual(vm_manager.ERROR, self.vm_mgr.state)

    @mock.patch('time.sleep')
    def test_boot_success_after_error(self, sleep):
        self.next_state = vm_manager.UP
        rtr = mock.sentinel.router
        self.ctx.neutron.get_router_detail.return_value = rtr
        rtr.id = 'ROUTER1'
        rtr.management_port = None
        rtr.external_port = None
        rtr.ports = mock.MagicMock()
        rtr.ports.__iter__.return_value = []
        self.vm_mgr.set_error(self.ctx)
        self.vm_mgr.boot(self.ctx)
        self.assertEqual(self.vm_mgr.state, vm_manager.DOWN)  # async
        self.ctx.nova_client.reboot_router_instance.assert_called_once_with(
            self.vm_mgr.router_obj
        )


class TestBootAttemptCounter(unittest.TestCase):

    def setUp(self):
        self.c = vm_manager.BootAttemptCounter()

    def test_start(self):
        self.c.start()
        self.assertEqual(1, self.c._attempts)
        self.c.start()
        self.assertEqual(2, self.c._attempts)

    def test_reset(self):
        self.c._attempts = 2
        self.c.reset()
        self.assertEqual(0, self.c._attempts)
