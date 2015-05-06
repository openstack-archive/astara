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
from akanda.rug.api import neutron, nova

vm_manager.RETRY_DELAY = 0.4
vm_manager.BOOT_WAIT = 1

LOG = logging.getLogger(__name__)


class FakeModel(object):
    def __init__(self, id_, **kwargs):
        self.id = id_
        self.__dict__.update(kwargs)


fake_mgt_port = FakeModel(
    '1',
    mac_address='aa:bb:cc:dd:ee:ff',
    network_id='ext-net',
    fixed_ips=[FakeModel('', ip_address='9.9.9.9', subnet_id='s2')])


class TestVmManager(unittest.TestCase):

    def setUp(self):
        self.ctx = mock.Mock()
        self.neutron = self.ctx.neutron
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



        self.INSTANCE_INFO = nova.InstanceInfo(
            instance_id='fake_instance_id',
            name='fake_name',
            image_uuid='fake_image_id',
            booting=False,
            last_boot = datetime.utcnow() - timedelta(minutes=15),
            ports=(),
            management_port=fake_mgt_port,
        )

        self.mock_update_state = self.update_state_p.start()
        self.vm_mgr = vm_manager.VmManager('the_id', 'tenant_id',
                                           self.log, self.ctx)
        self.vm_mgr.instance_info = self.INSTANCE_INFO
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
        n = self.neutron

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

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_router_status_caching(self, config, get_mgt_addr, router_api):
        self.update_state_p.stop()
        router_api.is_alive.return_value = False
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        rtr.management_port = mock.Mock()
        rtr.external_port = mock.Mock()
        self.ctx.neutron.get_router_detail.return_value = rtr
        n = self.neutron

        # Router state should start down
        self.vm_mgr.update_state(self.ctx)
        n.update_router_status.assert_called_once_with('R1', 'DOWN')
        n.update_router_status.reset_mock()

        # Router state should not be updated in neutron if it didn't change
        self.vm_mgr.update_state(self.ctx)
        self.assertEqual(n.update_router_status.call_count, 0)

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    def test_boot_timeout_still_booting(self, router_api, sleep):
        now = datetime.utcnow()
        self.INSTANCE_INFO.last_boot = now
        self.vm_mgr.last_boot = now
        self.update_state_p.stop()
        router_api.is_alive.return_value = False

        self.assertEqual(
            self.vm_mgr.update_state(self.ctx),
            vm_manager.BOOTING
        )
        router_api.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
        ])

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    def test_boot_timeout_error(self, router_api, sleep):
        self.vm_mgr.state = vm_manager.ERROR
        self.vm_mgr.last_boot = datetime.utcnow()
        self.update_state_p.stop()
        router_api.is_alive.return_value = False

        self.assertEqual(
            self.vm_mgr.update_state(self.ctx),
            vm_manager.ERROR,
        )
        router_api.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
        ])

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    def test_boot_timeout_error_no_last_boot(self, router_api, sleep):
        self.vm_mgr.state = vm_manager.ERROR
        self.vm_mgr.last_boot = None
        self.update_state_p.stop()
        router_api.is_alive.return_value = False

        self.assertEqual(
            self.vm_mgr.update_state(self.ctx),
            vm_manager.ERROR,
        )
        router_api.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
        ])

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    def test_boot_timeout(self, router_api, sleep):
        self.vm_mgr.last_boot = datetime.utcnow() - timedelta(minutes=5)
        self.update_state_p.stop()
        router_api.is_alive.return_value = False

        self.assertEqual(self.vm_mgr.update_state(self.ctx), vm_manager.DOWN)
        router_api.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
            mock.call(self.INSTANCE_INFO.management_address, 5000),
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
        self.vm_mgr.boot(self.ctx, 'GLANCE-IMAGE-123')
        self.assertEqual(self.vm_mgr.state, vm_manager.BOOTING)  # async
#        self.ctx.nova_client.reboot_router_instance.assert_called_once_with(
#            self.vm_mgr.router_obj,
#            'GLANCE-IMAGE-123'
#        )
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
        self.vm_mgr.boot(self.ctx, 'GLANCE-IMAGE-123')
        self.assertEqual(self.vm_mgr.state, vm_manager.BOOTING)
#        self.ctx.nova_client.boot_instance.assert_called_once_with(
#            self.vm_mgr.router_obj,
#            'GLANCE-IMAGE-123'
#        )
        self.assertEqual(1, self.vm_mgr.attempts)

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
        self.vm_mgr.boot(self.ctx, 'GLANCE-IMAGE-123')
        self.assertEqual(self.vm_mgr.state, vm_manager.DOWN)
#        self.ctx.nova_client.boot_instance.assert_called_once_with(
#            self.vm_mgr.router_obj,
#            'GLANCE-IMAGE-123'
#        )
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
        self.vm_mgr.boot(self.ctx, 'GLANCE-IMAGE-123')
        self.assertEqual(self.vm_mgr.state, vm_manager.BOOTING)  # async
        self.ctx.nova_client.boot_instance.assert_called_once_with(
            self.INSTANCE_INFO,
            rtr.id,
            'GLANCE-IMAGE-123',
            mock.ANY,  # TODO(adam_g): actually test make_vrrp_ports()
        )

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

    @mock.patch('time.sleep')
    def test_stop_router_already_deleted_from_neutron(self, sleep):
        self.vm_mgr.state = vm_manager.GONE
        self.vm_mgr.stop(self.ctx)

        # Because the Router object is actually deleted from Neutron at this
        # point, an anonymous "fake" router (with an ID and tenant ID of the
        # deleted router) is created.  This allows us to pass an expected
        # object to the Nova API code to cleans up the orphaned router VM.
        args = self.ctx.nova_client.destroy_router_instance.call_args
        assert args[0][0].name == 'unnamed'
        self.assertEqual(self.vm_mgr.state, vm_manager.GONE)

    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_configure_success(self, config, router_api):
        rtr = mock.sentinel.router

        self.ctx.neutron.get_router_detail.return_value = rtr
        config.return_value = 'fake_config'
        router_api.get_interfaces.return_value = []

        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = True
            self.vm_mgr.configure(self.ctx)

            verify.assert_called_once_with(rtr, [])
            config.assert_called_once_with(self.ctx.neutron, rtr, fake_mgt_port, {})
            router_api.update_config.assert_called_once_with(
                self.INSTANCE_INFO.management_address, 5000, 'fake_config',
            )
            self.assertEqual(self.vm_mgr.state, vm_manager.CONFIGURED)

    @mock.patch('akanda.rug.vm_manager.router_api')
    def test_configure_mismatched_interfaces(self, router_api):
        rtr = mock.sentinel.router

        self.neutron.get_router_detail.return_value = rtr

        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = False
            self.vm_mgr.configure(self.ctx)

            interfaces = router_api.get_interfaces.return_value

            verify.assert_called_once_with(rtr, interfaces)

            self.assertFalse(router_api.update_config.called)
            self.assertEqual(self.vm_mgr.state, vm_manager.REPLUG)

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_configure_failure(self, config, router_api, sleep):
        rtr = {'id': 'the_id'}

        self.neutron.get_router_detail.return_value = rtr

        router_api.update_config.side_effect = Exception
        config.return_value = 'fake_config'

        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = True
            self.vm_mgr.configure(self.ctx)

            interfaces = router_api.get_interfaces.return_value
            verify.assert_called_once_with(rtr, interfaces)

            config.assert_called_once_with(self.neutron, rtr, fake_mgt_port, {})
            expected_calls = [
                mock.call(self.INSTANCE_INFO.management_address, 5000,
                'fake_config') for i in range(0, 2)]
            router_api.update_config.assert_has_calls(expected_calls)
            self.assertEqual(self.vm_mgr.state, vm_manager.RESTART)

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_replug_add_new_port_success(self, get_mgt_addr, router_api):
        self.vm_mgr.state = vm_manager.REPLUG
        get_mgt_addr.return_value = 'fe80::beef'
        rtr = mock.sentinel.router
        rtr.management_port = mock.Mock()
        rtr.external_port = mock.Mock()
        rtr.management_port.mac_address = 'a:b:c:d'
        rtr.external_port.mac_address = 'd:c:b:a'
        p = mock.Mock()
        p.id = 'ABC'
        p.mac_address = 'a:a:a:a'
        p2 = mock.Mock()
        p2.id = 'DEF'
        p2.mac_address = 'b:b:b:b'
        rtr.internal_ports = [p, p2]

        self.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.router_obj = rtr
        router_api.get_interfaces.return_value = [
            {'lladdr': rtr.management_port.mac_address},
            {'lladdr': rtr.external_port.mac_address},
            {'lladdr': p.mac_address},
        ]
        self.conf.hotplug_timeout = 5

        get_instance = self.ctx.nova_client.get_instance
        get_instance.return_value = mock.Mock()
        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = True  # the hotplug worked!
            self.vm_mgr.replug(self.ctx)
            assert self.vm_mgr.state == vm_manager.REPLUG

            get_instance.return_value.interface_attach.assert_called_once_with(
                p2.id, None, None
            )

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.vm_manager.router_api')
    def test_replug_add_new_port_failure(self, router_api):
        self.vm_mgr.state = vm_manager.REPLUG
        rtr = mock.sentinel.router
        rtr.management_port = mock.Mock()
        rtr.external_port = mock.Mock()
        rtr.management_port.mac_address = 'a:b:c:d'
        rtr.external_port.mac_address = 'd:c:b:a'
        p = mock.Mock()
        p.id = 'ABC'
        p.mac_address = 'a:a:a:a'
        p2 = mock.Mock()
        p2.id = 'DEF'
        p2.mac_address = 'b:b:b:b'
        rtr.internal_ports = [p, p2]

        self.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.router_obj = rtr
        router_api.get_interfaces.return_value = [
            {'lladdr': rtr.management_port.mac_address},
            {'lladdr': rtr.external_port.mac_address},
            {'lladdr': p.mac_address},
        ]
        self.conf.hotplug_timeout = 5

        get_instance = self.ctx.nova_client.get_instance
        get_instance.return_value = mock.Mock()
        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = False  # The hotplug didn't work!
            self.vm_mgr.replug(self.ctx)
            assert self.vm_mgr.state == vm_manager.RESTART

            get_instance.return_value.interface_attach.assert_called_once_with(
                p2.id, None, None
            )

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_replug_with_missing_external_port(self, get_mgt_addr, router_api):
        """
        If the router doesn't have a management or external port, we should
        attempt to create (and plug) them.
        """
        self.vm_mgr.state = vm_manager.REPLUG
        get_mgt_addr.return_value = 'fe80::beef'
        rtr = mock.sentinel.router
        rtr.id = 'SOME-ROUTER-ID'
        rtr.management_port = None
        rtr.external_port = None
        self.ctx.neutron.create_router_management_port.return_value = \
            mock.Mock(mac_address='a:b:c:d')
        self.ctx.neutron.create_router_external_port.return_value = mock.Mock(
            mac_address='d:c:b:a'
        )
        p = mock.Mock()
        p.id = 'ABC'
        p.mac_address = 'a:a:a:a'
        p2 = mock.Mock()
        p2.id = 'DEF'
        p2.mac_address = 'b:b:b:b'
        rtr.internal_ports = [p, p2]

        self.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.router_obj = rtr
        router_api.get_interfaces.return_value = [
            {'lladdr': 'd:c:b:a'},
            {'lladdr': 'a:b:c:d'},
            {'lladdr': p.mac_address},
        ]
        self.conf.hotplug_timeout = 5

        get_instance = self.ctx.nova_client.get_instance
        get_instance.return_value = mock.Mock()
        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = True  # the hotplug worked!
            self.vm_mgr.replug(self.ctx)
            assert self.vm_mgr.state == vm_manager.REPLUG

            self.ctx.neutron.create_router_management_port.assert_called_with(
                'SOME-ROUTER-ID'
            )
            self.ctx.neutron.create_router_external_port.assert_called_with(
                rtr
            )
            get_instance.return_value.interface_attach.assert_called_once_with(
                p2.id, None, None
            )

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_replug_remove_port_success(self, get_mgt_addr, router_api):
        self.vm_mgr.state = vm_manager.REPLUG
        get_mgt_addr.return_value = 'fe80::beef'
        rtr = mock.sentinel.router
        rtr.management_port = mock.Mock()
        rtr.external_port = mock.Mock()
        rtr.management_port.mac_address = 'a:b:c:d'
        rtr.external_port.mac_address = 'd:c:b:a'
        p = mock.Mock()
        p.id = 'ABC'
        p.mac_address = 'a:a:a:a'
        rtr.internal_ports = []

        self.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.router_obj = rtr
        router_api.get_interfaces.return_value = [
            {'lladdr': rtr.management_port.mac_address},
            {'lladdr': rtr.external_port.mac_address},
            {'lladdr': p.mac_address}
        ]
        self.conf.hotplug_timeout = 5

        get_instance = self.ctx.nova_client.get_instance
        get_instance.return_value = mock.Mock()
        self.ctx.neutron.api_client.list_ports.return_value = {
            'ports': [{
                'id': p.id,
                'device_id': 'INSTANCE123',
                'fixed_ips': [],
                'mac_address': p.mac_address,
                'network_id': 'NETWORK123',
                'device_owner': 'network:router_interface'
            }]
        }
        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = True  # the unplug worked!
            self.vm_mgr.replug(self.ctx)
            assert self.vm_mgr.state == vm_manager.REPLUG

            get_instance.return_value.interface_detach.assert_called_once_with(
                p.id
            )

    @mock.patch('time.sleep', lambda *a: None)
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_replug_remove_port_failure(self, get_mgt_addr, router_api):
        self.vm_mgr.state = vm_manager.REPLUG
        get_mgt_addr.return_value = 'fe80::beef'
        rtr = mock.sentinel.router
        rtr.management_port = mock.Mock()
        rtr.external_port = mock.Mock()
        rtr.management_port.mac_address = 'a:b:c:d'
        rtr.external_port.mac_address = 'd:c:b:a'
        p = mock.Mock()
        p.id = 'ABC'
        p.mac_address = 'a:a:a:a'
        rtr.internal_ports = []

        self.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.router_obj = rtr
        router_api.get_interfaces.return_value = [
            {'lladdr': rtr.management_port.mac_address},
            {'lladdr': rtr.external_port.mac_address},
            {'lladdr': p.mac_address}
        ]
        self.conf.hotplug_timeout = 5

        get_instance = self.ctx.nova_client.get_instance
        get_instance.return_value = mock.Mock()
        self.ctx.neutron.api_client.list_ports.return_value = {
            'ports': [{
                'id': p.id,
                'device_id': 'INSTANCE123',
                'fixed_ips': [],
                'mac_address': p.mac_address,
                'network_id': 'NETWORK123',
                'device_owner': 'network:router_interface'
            }]
        }
        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = False  # the unplug failed!
            self.vm_mgr.replug(self.ctx)
            assert self.vm_mgr.state == vm_manager.RESTART

            get_instance.return_value.interface_detach.assert_called_once_with(
                p.id
            )

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
        rtr.external_port = None
        self.assertEqual(self.vm_mgr._ensure_provider_ports(rtr, self.ctx),
                         rtr)
        self.neutron.create_router_external_port.assert_called_once_with(rtr)

    def test_set_error_when_gone(self):
        self.vm_mgr.state = vm_manager.GONE
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.set_error(self.ctx)
        self.neutron.update_router_status.assert_called_once_with('R1',
                                                                  'ERROR')
        self.assertEqual(vm_manager.GONE, self.vm_mgr.state)

    def test_set_error_when_booting(self):
        self.vm_mgr.state = vm_manager.BOOTING
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.set_error(self.ctx)
        self.neutron.update_router_status.assert_called_once_with('R1',
                                                                  'ERROR')
        self.assertEqual(vm_manager.ERROR, self.vm_mgr.state)

    def test_clear_error_when_gone(self):
        self.vm_mgr.state = vm_manager.GONE
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.clear_error(self.ctx)
        self.neutron.update_router_status.assert_called_once_with('R1',
                                                                  'ERROR')
        self.assertEqual(vm_manager.GONE, self.vm_mgr.state)

    def test_set_error_when_error(self):
        self.vm_mgr.state = vm_manager.ERROR
        rtr = mock.sentinel.router
        rtr.id = 'R1'
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.vm_mgr.clear_error(self.ctx)
        self.neutron.update_router_status.assert_called_once_with('R1',
                                                                  'DOWN')
        self.assertEqual(vm_manager.DOWN, self.vm_mgr.state)

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
        self.vm_mgr.boot(self.ctx, 'GLANCE-IMAGE-123')
        self.assertEqual(self.vm_mgr.state, vm_manager.BOOTING)  # async
#        self.ctx.nova_client.reboot_router_instance.assert_called_once_with(
#            self.vm_mgr.router_obj,
#            'GLANCE-IMAGE-123'
#        )

    def test_error_cooldown(self):
        self.conf.error_state_cooldown = 30
        self.assertIsNone(self.vm_mgr.last_error)
        self.assertFalse(self.vm_mgr.error_cooldown)

        self.vm_mgr.state = vm_manager.ERROR
        self.vm_mgr.last_error = datetime.utcnow() - timedelta(seconds=1)
        self.assertTrue(self.vm_mgr.error_cooldown)

        self.vm_mgr.last_error = datetime.utcnow() - timedelta(minutes=5)
        self.assertFalse(self.vm_mgr.error_cooldown)


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


class TestSynchronizeRouterStatus(unittest.TestCase):

    def setUp(self):
        self.test_vm_manager = mock.Mock(spec=('router_obj',
                                               '_last_synced_status',
                                               'state'))
        self.test_context = mock.Mock()

    def test_router_is_deleted(self):
        self.test_vm_manager.router_obj = None
        v = vm_manager.synchronize_router_status(
            lambda vm_manager_inst, ctx, silent: 1)
        self.assertEqual(v(self.test_vm_manager, {}), 1)

    def test_router_status_changed(self):
        self.test_vm_manager.router_obj = mock.Mock(id='ABC123')
        self.test_vm_manager._last_synced_status = neutron.STATUS_ACTIVE
        self.test_vm_manager.state = vm_manager.DOWN
        v = vm_manager.synchronize_router_status(
            lambda vm_manager_inst, ctx, silent: 1)
        self.assertEqual(v(self.test_vm_manager, self.test_context), 1)
        self.test_context.neutron.update_router_status.\
            assert_called_once_with(
                'ABC123',
                neutron.STATUS_DOWN)
        self.assertEqual(self.test_vm_manager._last_synced_status,
                         neutron.STATUS_DOWN)

    def test_router_status_same(self):
        self.test_vm_manager.router_obj = mock.Mock(id='ABC123')
        self.test_vm_manager._last_synced_status = neutron.STATUS_ACTIVE
        self.test_vm_manager.state = vm_manager.CONFIGURED
        v = vm_manager.synchronize_router_status(
            lambda vm_manager_inst, ctx, silent: 1)
        self.assertEqual(v(self.test_vm_manager, self.test_context), 1)
        self.assertEqual(
            self.test_context.neutron.update_router_status.call_count, 0)
        self.assertEqual(
            self.test_vm_manager._last_synced_status, neutron.STATUS_ACTIVE)
