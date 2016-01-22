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

import mock
import unittest2 as unittest
from datetime import datetime, timedelta

from astara import instance_manager
from astara.api import nova
from astara.drivers import states
from astara.test.unit import base
from astara.test.unit import fakes

from oslo_config import cfg

states.RETRY_DELAY = 0.4
states.BOOT_WAIT = 1


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


class TestInstanceManager(base.RugTestBase):

    def setUp(self):
        super(TestInstanceManager, self).setUp()
        self.conf = cfg.CONF
        self.fake_driver = fakes.fake_driver()
        self.ctx = mock.Mock()
        self.neutron = self.ctx.neutron
        self.config(boot_timeout=30)
        self.config(astara_mgt_service_port=5000)
        self.config(max_retries=3)
        self.addCleanup(mock.patch.stopall)

        self.log = mock.Mock()
        self.update_state_p = mock.patch.object(
            instance_manager.InstanceManager,
            'update_state'
        )

        ports = [fake_int_port, fake_ext_port]

        self.fake_driver.get_interfaces.return_value = [
            {'ifname': 'ge0', 'lladdr': fake_mgt_port.mac_address},
            {'ifname': 'ge1', 'lladdr': fake_ext_port.mac_address},
            {'ifname': 'ge2', 'lladdr': fake_int_port.mac_address},
        ]
        self.fake_driver.ports = ports

        self.INSTANCE_INFO = nova.InstanceInfo(
            instance_id='fake_instance_id',
            name='ak-router-83f16d4c-66d8-11e5-938a-525400cfc326',
            management_port=fake_mgt_port,
            ports=[fake_int_port, fake_ext_port, fake_mgt_port],
            image_uuid='9f3dbe8e-66d8-11e5-9952-525400cfc326',
            status='ACTIVE',
            last_boot=(datetime.utcnow() - timedelta(minutes=15)),
        )

        self.ctx.nova_client.get_instance_info.return_value = (
            self.INSTANCE_INFO)
        self.ctx.nova_client.get_instance_info_for_obj.return_value = (
            self.INSTANCE_INFO)
        self.ctx.neutron.get_ports_for_instance.return_value = (
            fake_mgt_port, [fake_int_port, fake_ext_port])

        self.mock_update_state = self.update_state_p.start()
        self.instance_mgr = instance_manager.InstanceManager(
            self.fake_driver,
            'fake_resource_id',
            self.ctx
        )
        self.instance_mgr.instance_info = self.INSTANCE_INFO

        self.next_state = None

        def next_state(*args, **kwargs):
            if self.next_state:
                self.instance_mgr.state = self.next_state
            return self.instance_mgr.state
        self.mock_update_state.side_effect = next_state

    def test_update_state_is_alive(self):
        self.update_state_p.stop()
        self.fake_driver.is_alive.return_value = True

        self.assertEqual(self.instance_mgr.update_state(self.ctx),
                         states.UP)
        self.fake_driver.is_alive.assert_called_once_with(
            self.INSTANCE_INFO.management_address)

    def test_update_state_no_backing_instance(self):
        # this tests that a mgr gets its instance_info updated to None
        # when the backing instance is no longer present.
        self.instance_mgr.instance_info = None
        self.ctx.nova_client.get_instance_info.return_value = None
        self.update_state_p.stop()
        self.assertEqual(self.instance_mgr.update_state(self.ctx),
                         states.DOWN)
        self.assertFalse(self.fake_driver.is_alive.called)

    def test_update_state_instance_no_ports_still_booting(self):
        self.update_state_p.stop()
        self.ctx.nova_client.get_instance_info_for_obj.return_value = \
            self.INSTANCE_INFO
        self.ctx.neutron.get_ports_for_instance.return_value = (None, [])

        self.assertEqual(self.instance_mgr.update_state(self.ctx),
                         states.BOOTING)
        self.assertFalse(self.fake_driver.is_alive.called)

    def test_update_state_log_boot_time_once(self):
        self.update_state_p.stop()
        self.instance_mgr.log = mock.Mock(
            info=mock.Mock())
        self.ctx.nova_client.update_instance_info.return_value = (
            self.INSTANCE_INFO)
        self.instance_mgr.state = states.CONFIGURED
        self.fake_driver.is_alive.return_value = True
        self.instance_mgr.update_state(self.ctx)
        self.assertEqual(
            len(self.instance_mgr.log.info.call_args_list),
            1)
        self.instance_mgr.update_state(self.ctx)
        self.assertEqual(
            len(self.instance_mgr.log.info.call_args_list),
            1)

    @mock.patch('time.sleep', lambda *a: None)
    def test_router_status_sync(self):
        self.ctx.nova_client.update_instance_info.return_value = (
            self.INSTANCE_INFO)
        self.update_state_p.stop()
        self.fake_driver.is_alive.return_value = False

        # Router state should start down
        self.instance_mgr.update_state(self.ctx)
        self.fake_driver.synchronize_state.assert_called_with(
            self.ctx,
            state='down',
        )
        self.fake_driver.synchronize_state.reset_mock()

        # Bring the router to UP with `is_alive = True`
        self.fake_driver.is_alive.return_value = True
        self.instance_mgr.update_state(self.ctx)
        self.fake_driver.synchronize_state.assert_called_with(
            self.ctx,
            state='up',
        )
        self.fake_driver.synchronize_state.reset_mock()

        # Configure the router and make sure state is synchronized as ACTIVE
        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = True
            self.instance_mgr.last_boot = datetime.utcnow()
            self.instance_mgr.configure(self.ctx)
            self.instance_mgr.update_state(self.ctx)
            self.fake_driver.synchronize_state.assert_called_with(
                self.ctx,
                state='configured',
            )
            self.fake_driver.synchronize_state.reset_mock()

    @mock.patch('time.sleep', lambda *a: None)
    def test_router_status_caching(self):
        self.update_state_p.stop()
        self.fake_driver.is_alive.return_value = False

        # Router state should start down
        self.instance_mgr.update_state(self.ctx)
        self.fake_driver.synchronize_state.assert_called_once_with(
            self.ctx, state='down')

    @mock.patch('time.sleep')
    def test_boot_timeout_still_booting(self, sleep):
        now = datetime.utcnow()
        self.INSTANCE_INFO.last_boot = now
        self.instance_mgr.last_boot = now
        self.update_state_p.stop()
        self.fake_driver.is_alive.return_value = False

        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.BOOTING
        )
        self.fake_driver.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address),
            mock.call(self.INSTANCE_INFO.management_address),
            mock.call(self.INSTANCE_INFO.management_address),
        ])

    @mock.patch('time.sleep')
    def test_boot_timeout_error(self, sleep):
        self.instance_mgr.state = states.ERROR
        self.instance_mgr.last_boot = datetime.utcnow()
        self.update_state_p.stop()
        self.fake_driver.is_alive.return_value = False

        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.ERROR,
        )
        self.fake_driver.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address),
            mock.call(self.INSTANCE_INFO.management_address),
            mock.call(self.INSTANCE_INFO.management_address),
        ])

    @mock.patch('time.sleep')
    def test_boot_timeout_error_no_last_boot(self, sleep):
        self.instance_mgr.state = states.ERROR
        self.instance_mgr.last_boot = None
        self.update_state_p.stop()
        self.fake_driver.is_alive.return_value = False

        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.ERROR,
        )
        self.fake_driver.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address),
            mock.call(self.INSTANCE_INFO.management_address),
            mock.call(self.INSTANCE_INFO.management_address),
        ])

    @mock.patch('time.sleep')
    def test_boot_timeout(self, sleep):
        self.instance_mgr.last_boot = datetime.utcnow() - timedelta(minutes=5)
        self.update_state_p.stop()
        self.fake_driver.is_alive.return_value = False

        self.assertEqual(self.instance_mgr.update_state(self.ctx),
                         states.DOWN)
        self.fake_driver.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address),
            mock.call(self.INSTANCE_INFO.management_address),
            mock.call(self.INSTANCE_INFO.management_address),
        ])
        self.instance_mgr.log.info.assert_called_once_with(
            mock.ANY,
            self.conf.boot_timeout,
        )

    @mock.patch('time.sleep')
    def test_update_state_is_down(self, sleep):
        self.update_state_p.stop()
        self.fake_driver.is_alive.return_value = False

        self.assertEqual(self.instance_mgr.update_state(self.ctx),
                         states.DOWN)
        self.fake_driver.is_alive.assert_has_calls([
            mock.call(self.INSTANCE_INFO.management_address),
            mock.call(self.INSTANCE_INFO.management_address),
            mock.call(self.INSTANCE_INFO.management_address),
        ])

    @mock.patch('time.sleep')
    def test_update_state_retry_delay(self, sleep):
        self.update_state_p.stop()
        self.fake_driver.is_alive.side_effect = [False, False, True]
        max_retries = 5
        self.conf.max_retries = max_retries
        self.instance_mgr.update_state(self.ctx, silent=False)
        self.assertEqual(sleep.call_count, 2)

    @mock.patch('time.sleep')
    def test_boot_success(self, sleep):
        self.next_state = states.UP
        self.instance_mgr.boot(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.BOOTING)

        self.ctx.nova_client.boot_instance.assert_called_once_with(
            resource_type=self.fake_driver.RESOURCE_NAME,
            prev_instance_info=self.INSTANCE_INFO,
            name=self.fake_driver.name,
            image_uuid=self.fake_driver.image_uuid,
            flavor=self.fake_driver.flavor,
            make_ports_callback='fake_ports_callback')

        self.assertEqual(1, self.instance_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_instance_deleted(self, sleep):
        self.ctx.nova_client.boot_instance.return_value = None
        self.instance_mgr.boot(self.ctx)
        # a deleted VM should reset the vm mgr state and not as a failed
        # attempt
        self.assertEqual(self.instance_mgr.attempts, 0)
        self.assertIsNone(self.instance_mgr.instance_info)

    @mock.patch('time.sleep')
    def test_boot_fail(self, sleep):
        self.next_state = states.DOWN
        self.instance_mgr.boot(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.BOOTING)
        self.ctx.nova_client.boot_instance.assert_called_once_with(
            resource_type=self.fake_driver.RESOURCE_NAME,
            prev_instance_info=self.INSTANCE_INFO,
            name=self.fake_driver.name,
            image_uuid=self.fake_driver.image_uuid,
            flavor=self.fake_driver.flavor,
            make_ports_callback='fake_ports_callback')
        self.assertEqual(1, self.instance_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_exception(self, sleep):
        self.ctx.nova_client.boot_instance.side_effect = RuntimeError
        self.instance_mgr.boot(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.DOWN)
        self.ctx.nova_client.boot_instance.assert_called_once_with(
            resource_type=self.fake_driver.RESOURCE_NAME,
            prev_instance_info=self.INSTANCE_INFO,
            name=self.fake_driver.name,
            image_uuid=self.fake_driver.image_uuid,
            flavor=self.fake_driver.flavor,
            make_ports_callback='fake_ports_callback')
        self.assertEqual(1, self.instance_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_with_port_cleanup(self, sleep):
        self.next_state = states.UP

        management_port = mock.Mock(id='mgmt', device_id='INSTANCE1')
        external_port = mock.Mock(id='ext', device_id='INSTANCE1')
        internal_port = mock.Mock(id='int', device_id='INSTANCE1')

        rtr = mock.sentinel.router
        instance = mock.sentinel.instance
        self.ctx.neutron.get_router_detail.return_value = rtr
        self.ctx.nova_client.get_instance.return_value = instance
        self.ctx.nova_client.boot_instance.side_effect = RuntimeError
        rtr.id = 'ROUTER1'
        instance.id = 'INSTANCE1'
        rtr.management_port = management_port
        rtr.external_port = external_port
        rtr.ports = mock.MagicMock()
        rtr.ports.__iter__.return_value = [management_port, external_port,
                                           internal_port]
        self.instance_mgr.boot(self.ctx)
        self.ctx.nova_client.boot_instance.assert_called_once_with(
            resource_type=self.fake_driver.RESOURCE_NAME,
            prev_instance_info=self.INSTANCE_INFO,
            name=self.fake_driver.name,
            image_uuid=self.fake_driver.image_uuid,
            flavor=self.fake_driver.flavor,
            make_ports_callback='fake_ports_callback')
        self.instance_mgr.driver.delete_ports.assert_called_once_with(self.ctx)

    def test_boot_check_up(self):
        with mock.patch.object(
            instance_manager.InstanceManager,
            'update_state'
        ) as update_state:
            with mock.patch.object(
                instance_manager.InstanceManager,
                'configure'
            ) as configure:
                update_state.return_value = states.UP
                configure.side_effect = lambda *a, **kw: setattr(
                    self.instance_mgr,
                    'state',
                    states.CONFIGURED
                )
                assert self.instance_mgr.check_boot(self.ctx) is True
                update_state.assert_called_once_with(self.ctx, silent=True)
                configure.assert_called_once_with(self.ctx)

    def test_boot_check_configured(self):
        with mock.patch.object(
            instance_manager.InstanceManager,
            'update_state'
        ) as update_state:
            with mock.patch.object(
                instance_manager.InstanceManager,
                'configure'
            ) as configure:
                update_state.return_value = states.CONFIGURED
                configure.side_effect = lambda *a, **kw: setattr(
                    self.instance_mgr,
                    'state',
                    states.CONFIGURED
                )
                assert self.instance_mgr.check_boot(self.ctx) is True
                update_state.assert_called_once_with(self.ctx, silent=True)
                configure.assert_called_once_with(self.ctx)

    def test_boot_check_still_booting(self):
        with mock.patch.object(
            instance_manager.InstanceManager,
            'update_state'
        ) as update_state:
            update_state.return_value = states.BOOTING
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
                update_state.return_value = states.CONFIGURED
                configure.side_effect = lambda *a, **kw: setattr(
                    self.instance_mgr,
                    'state',
                    states.BOOTING
                )
                assert self.instance_mgr.check_boot(self.ctx) is False
                update_state.assert_called_once_with(self.ctx, silent=True)
                configure.assert_called_once_with(self.ctx)

    @mock.patch('time.sleep')
    def test_stop_success(self, sleep):
        self.instance_mgr.state = states.UP
        self.ctx.nova_client.get_instance_by_id.return_value = None
        self.instance_mgr.stop(self.ctx)
        self.ctx.nova_client.destroy_instance.assert_called_once_with(
            self.INSTANCE_INFO
        )
        self.instance_mgr.driver.delete_ports.assert_called_once_with(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.DOWN)

    @mock.patch('time.time')
    @mock.patch('time.sleep')
    def test_stop_fail(self, sleep, time):
        t = 1444679566
        side_effects = [t]
        for i in range(30):
            t = t + 1
            side_effects.append(t)
        time.side_effect = side_effects
        self.config(boot_timeout=30)
        self.instance_mgr.state = states.UP
        self.ctx.nova_client.get_router_instance_status.return_value = 'UP'
        self.instance_mgr.stop(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.UP)
        self.ctx.nova_client.destroy_instance.assert_called_once_with(
            self.INSTANCE_INFO
        )

    @mock.patch('time.sleep')
    def test_stop_router_already_deleted_from_neutron(self, sleep):
        self.instance_mgr.state = states.GONE
        self.ctx.nova_client.get_instance_by_id.return_value = None
        self.instance_mgr.stop(self.ctx)
        self.ctx.nova_client.destroy_instance.assert_called_once_with(
            self.INSTANCE_INFO)
        self.ctx.nova_client.get_instance_by_id.assert_called_with(
            self.INSTANCE_INFO.id_
        )
        self.assertEqual(self.instance_mgr.state, states.GONE)

    def test_configure_success(self):
        self.fake_driver.build_config.return_value = 'fake_config'
        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = True
            self.instance_mgr.configure(self.ctx)

            verify.assert_called_once_with(
                self.fake_driver.ports,
                self.fake_driver.get_interfaces.return_value)

            self.fake_driver.build_config.assert_called_once_with(
                self.ctx,
                self.INSTANCE_INFO.management_port,
                {'ext-net': 'ge1', 'int-net': 'ge2', 'mgt-net': 'ge0'})
            self.fake_driver.update_config.assert_called_once_with(
                self.INSTANCE_INFO.management_address, 'fake_config',
            )
            self.assertEqual(self.instance_mgr.state,
                             states.CONFIGURED)

    def test_configure_mismatched_interfaces(self):
        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = False
            self.instance_mgr.configure(self.ctx)

            verify.assert_called_once_with(
                self.fake_driver.ports,
                self.fake_driver.get_interfaces.return_value)

            self.assertFalse(self.fake_driver.update_config.called)
            self.assertEqual(self.instance_mgr.state, states.REPLUG)

    @mock.patch('time.sleep')
    def test_configure_failure(self, sleep):

        self.fake_driver.update_config.side_effect = Exception
        self.fake_driver.build_config.return_value = 'fake_config'

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = True
            self.instance_mgr.configure(self.ctx)

            interfaces = self.fake_driver.get_interfaces.return_value
            verify.assert_called_once_with(
                self.fake_driver.ports, interfaces)

            expected_calls = [
                mock.call(self.INSTANCE_INFO.management_address,
                          'fake_config')
                for i in range(0, 2)]
            self.fake_driver.update_config.assert_has_calls(expected_calls)
            self.assertEqual(self.instance_mgr.state, states.RESTART)

    @mock.patch('time.sleep', lambda *a: None)
    def test_replug_add_new_port_success(self):
        self.instance_mgr.state = states.REPLUG

        self.fake_driver.get_interfaces.return_value = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
            {'lladdr': fake_int_port.mac_address}
        ]
        self.conf.hotplug_timeout = 5

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)
        fake_new_port = fake_add_port
        self.fake_driver.ports.append(fake_new_port)
        self.ctx.neutron.create_vrrp_port.return_value = fake_new_port

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = True  # the hotplug worked!
            self.instance_mgr.replug(self.ctx)

            self.ctx.neutron.create_vrrp_port.assert_called_with(
                self.fake_driver.id, 'additional-net'
            )
            self.assertEqual(self.instance_mgr.state, states.REPLUG)
            fake_instance.interface_attach.assert_called_once_with(
                fake_new_port.id, None, None
            )
            self.assertIn(fake_new_port, self.INSTANCE_INFO.ports)

    @mock.patch('time.sleep', lambda *a: None)
    def test_replug_add_new_port_failure(self):
        self.instance_mgr.state = states.REPLUG

        self.fake_driver.get_interfaces.return_value = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
            {'lladdr': fake_int_port.mac_address}
        ]
        self.conf.hotplug_timeout = 5

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)

        fake_new_port = fake_add_port
        self.fake_driver.ports.append(fake_new_port)
        self.ctx.neutron.create_vrrp_port.return_value = fake_new_port

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = False  # The hotplug didn't work!
            self.instance_mgr.replug(self.ctx)
            self.assertEqual(self.instance_mgr.state, states.RESTART)

            fake_instance.interface_attach.assert_called_once_with(
                fake_new_port.id, None, None
            )

    @mock.patch('time.sleep', lambda *a: None)
    def test_replug_remove_port_success(self):
        self.instance_mgr.state = states.REPLUG

        # Resource lacks the fake_ext_port, it will be unplugged
        self.fake_driver.ports = [fake_mgt_port, fake_int_port]
        self.fake_driver.get_interfaces.return_value = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_int_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
        ]
        self.conf.hotplug_timeout = 5

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)

        with mock.patch.object(self.instance_mgr,
                               '_verify_interfaces') as verify:
            verify.return_value = True  # the unplug worked!
            self.instance_mgr.replug(self.ctx)
            self.assertEqual(self.instance_mgr.state, states.REPLUG)
            fake_instance.interface_detach.assert_called_once_with(
                fake_ext_port.id
            )
            self.assertNotIn(fake_ext_port, self.INSTANCE_INFO.ports)

    @mock.patch('time.sleep', lambda *a: None)
    def test_replug_remove_port_failure(self):
        self.instance_mgr.state = states.REPLUG

        # Router lacks the fake_ext_port, it will be unplugged
        self.fake_driver.ports = [fake_mgt_port, fake_int_port]
        self.fake_driver.get_interfaces.return_value = [
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
            self.assertEqual(self.instance_mgr.state,
                             states.RESTART)
            fake_instance.interface_detach.assert_called_once_with(
                fake_ext_port.id
            )

    def test_verify_interfaces(self):
        self.fake_driver.ports = [fake_mgt_port, fake_ext_port, fake_int_port]
        interfaces = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
            {'lladdr': fake_int_port.mac_address}
        ]

        self.assertTrue(self.instance_mgr._verify_interfaces(
            self.fake_driver.ports, interfaces))

    def test_verify_interfaces_with_cleared_gateway(self):
        self.fake_driver.ports = [fake_mgt_port, fake_ext_port, fake_int_port]

        interfaces = [
            {'lladdr': 'a:b:c:d'},
            {'lladdr': 'd:c:b:a'},
            {'lladdr': 'a:a:a:a'}
        ]

        self.assertFalse(self.instance_mgr._verify_interfaces(
            self.fake_driver.ports, interfaces))

    def test_set_error_when_booting(self):
        self.instance_mgr.state = states.BOOTING
        self.instance_mgr.set_error(self.ctx)
        self.fake_driver.synchronize_state.assert_called_once_with(
            self.ctx, state='error')
        self.assertEqual(states.ERROR, self.instance_mgr.state)

    def test_clear_error_when_gone(self):
        self.instance_mgr.state = states.GONE
        self.instance_mgr.clear_error(self.ctx)
        self.fake_driver.synchronize_state(self.ctx, 'error')
        self.assertEqual(states.DOWN, self.instance_mgr.state)

    @mock.patch('time.sleep')
    def test_boot_success_after_error(self, sleep):
        self.next_state = states.UP
        rtr = mock.sentinel.router
        self.ctx.neutron.get_router_detail.return_value = rtr
        rtr.id = 'ROUTER1'
        rtr.management_port = None
        rtr.external_port = None
        rtr.ports = mock.MagicMock()
        rtr.ports.__iter__.return_value = []
        self.instance_mgr.set_error(self.ctx)
        self.instance_mgr.boot(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.BOOTING)

        self.ctx.nova_client.boot_instance.assert_called_once_with(
            resource_type=self.fake_driver.RESOURCE_NAME,
            prev_instance_info=self.INSTANCE_INFO,
            name=self.fake_driver.name,
            image_uuid=self.fake_driver.image_uuid,
            flavor=self.fake_driver.flavor,
            make_ports_callback='fake_ports_callback')

    def test_error_cooldown(self):
        self.config(error_state_cooldown=30)
        self.assertIsNone(self.instance_mgr.last_error)
        self.assertFalse(self.instance_mgr.error_cooldown)

        self.instance_mgr.state = states.ERROR
        self.instance_mgr.last_error = datetime.utcnow() - timedelta(seconds=1)
        self.assertTrue(self.instance_mgr.error_cooldown)

        self.instance_mgr.last_error = datetime.utcnow() - timedelta(minutes=5)
        self.assertFalse(self.instance_mgr.error_cooldown)

    def test__ensure_cache(self):
        self.instance_mgr.instance_info = 'stale_info'
        self.ctx.nova_client.get_instance_info.return_value = \
            self.INSTANCE_INFO
        self.instance_mgr._ensure_cache(self.ctx)
        self.assertEqual(self.instance_mgr.instance_info, self.INSTANCE_INFO)


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
