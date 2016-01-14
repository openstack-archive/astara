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
import six
import uuid

import unittest2 as unittest

from datetime import datetime, timedelta
from six.moves import range

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


def instance_info():
        name = 'ak-router-' + str(uuid.uuid4())
        return nova.InstanceInfo(
            instance_id=str(uuid.uuid4()),
            name=name,
            management_port=fake_mgt_port,
            ports=[fake_int_port, fake_ext_port],
            image_uuid='9f3dbe8e-66d8-11e5-9952-525400cfc326',
            status='ACTIVE',
            last_boot=(datetime.utcnow() - timedelta(minutes=15)),
        )


class TestInstanceManager(base.RugTestBase):

    def setUp(self):
        super(TestInstanceManager, self).setUp()
        self.conf = cfg.CONF
        self.fake_driver = fakes.fake_driver()
        self.ctx = fakes.fake_worker_context()

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

        self.mock_update_state = self.update_state_p.start()
        self.instance_mgr = instance_manager.InstanceManager(
            self.fake_driver,
            self.ctx
        )
        self.instances_patch = mock.patch.object(
            instance_manager, 'InstanceGroupManager', autospec=True)
        self.instance_mgr.instances = self.instances_patch.start()

        self.next_state = None

        def next_state(*args, **kwargs):
            if self.next_state:
                self.instance_mgr.state = self.next_state
            return self.instance_mgr.state
        self.mock_update_state.side_effect = next_state

    def set_instances_container_mocks(self, instances=None, mocks=None):
        # set up a mock InstanceGroupManager based on dict
        # with specified mocks
        self.instances_patch.stop()

        mocks = mocks or []
        instances = instances or []

        class FakeInstancesContainer(dict):
            @property
            def instance_count(self):
                return len(self.values())

            @property
            def cluster_degraded(self):
                return len(self.values()) < self.count

            def remove(self, worker_context, instance):
                self.pop(instance.id_)

        self.instance_mgr.instances = FakeInstancesContainer()
        for attr, _mock in mocks:
            if attr not in dir(instance_manager.InstanceGroupManager):
                raise AttributeError(
                    'Attempting to mock non-existent method: %s' % attr)
            setattr(self.instance_mgr.instances, attr, _mock)

        self.instance_mgr.instances.update({
            i.id_: i for i in instances
        })
        self.instance_mgr.instances.count = len(instances)

#    def test_update_state_is_alive(self):
#        self.update_state_p.stop()
#        self.fake_driver.is_alive.return_value = True
#
#        self.assertEqual(self.instance_mgr.update_state(self.ctx),
#                         states.UP)
#        self.fake_driver.is_alive.assert_called_once_with(
#            self.INSTANCE_INFO.management_address)
#
#    def test_update_state_no_backing_instance(self):
#        # this tests that a mgr gets its instance_info updated to None
#        # when the backing instance is no longer present.
#        self.instance_mgr.instance_info = None
#        self.ctx.nova_client.get_instance_info.return_value = None
#        self.update_state_p.stop()
#        self.assertEqual(self.instance_mgr.update_state(self.ctx),
#                         states.DOWN)
#        self.assertFalse(self.fake_driver.is_alive.called)
#
#    def test_update_state_instance_no_ports_still_booting(self):
#        self.update_state_p.stop()
#        self.ctx.neutron.get_ports_for_instance.return_value = (None, [])
#
#        self.assertEqual(self.instance_mgr.update_state(self.ctx),
#                         states.BOOTING)
#        self.assertFalse(self.fake_driver.is_alive.called)
#
#    def test_update_state_log_boot_time_once(self):
#        self.update_state_p.stop()
#        self.instance_mgr.log = mock.Mock(
#            info=mock.Mock())
#        self.ctx.nova_client.update_instance_info.return_value = (
#            self.INSTANCE_INFO)
#        self.instance_mgr.state = states.CONFIGURED
#        self.fake_driver.is_alive.return_value = True
#        self.instance_mgr.update_state(self.ctx)
#        self.assertEqual(
#            len(self.instance_mgr.log.info.call_args_list),
#            1)
#        self.instance_mgr.update_state(self.ctx)
#        self.assertEqual(
#            len(self.instance_mgr.log.info.call_args_list),
#            1)
#
#    @mock.patch('time.sleep', lambda *a: None)
#    def test_router_status_sync(self):
#        self.ctx.nova_client.update_instance_info.return_value = (
#            self.INSTANCE_INFO)
#        self.update_state_p.stop()
#        self.fake_driver.is_alive.return_value = False
#
#        # Router state should start down
#        self.instance_mgr.update_state(self.ctx)
#        self.fake_driver.synchronize_state.assert_called_with(
#            self.ctx,
#            state='down',
#        )
#        self.fake_driver.synchronize_state.reset_mock()
#
#        # Bring the router to UP with `is_alive = True`
#        self.fake_driver.is_alive.return_value = True
#        self.instance_mgr.update_state(self.ctx)
#        self.fake_driver.synchronize_state.assert_called_with(
#            self.ctx,
#            state='up',
#        )
#        self.fake_driver.synchronize_state.reset_mock()
#        self.fake_driver.build_config.return_value = {}
#
#        # Configure the router and make sure state is synchronized as ACTIVE
#        with mock.patch.object(self.instance_mgr,
#                               '_verify_interfaces') as verify:
#            verify.return_value = True
#            self.instance_mgr.last_boot = datetime.utcnow()
#            self.instance_mgr.configure(self.ctx)
#            self.instance_mgr.update_state(self.ctx)
#            self.fake_driver.synchronize_state.assert_called_with(
#                self.ctx,
#                state='configured',
#            )
#            self.fake_driver.synchronize_state.reset_mock()
#
#    @mock.patch('time.sleep', lambda *a: None)
#    def test_router_status_caching(self):
#        self.update_state_p.stop()
#        self.fake_driver.is_alive.return_value = False
#
#        # Router state should start down
#        self.instance_mgr.update_state(self.ctx)
#        self.fake_driver.synchronize_state.assert_called_once_with(
#            self.ctx, state='down')
#
#    @mock.patch('time.sleep')
#    def test_boot_timeout_still_booting(self, sleep):
#        now = datetime.utcnow()
#        self.INSTANCE_INFO.last_boot = now
#        self.instance_mgr.last_boot = now
#        self.update_state_p.stop()
#        self.fake_driver.is_alive.return_value = False
#
#        self.assertEqual(
#            self.instance_mgr.update_state(self.ctx),
#            states.BOOTING
#        )
#        self.fake_driver.is_alive.assert_has_calls([
#            mock.call(self.INSTANCE_INFO.management_address),
#            mock.call(self.INSTANCE_INFO.management_address),
#            mock.call(self.INSTANCE_INFO.management_address),
#        ])
#
#    @mock.patch('time.sleep')
#    def test_boot_timeout_error(self, sleep):
#        self.instance_mgr.state = states.ERROR
#        self.instance_mgr.last_boot = datetime.utcnow()
#        self.update_state_p.stop()
#        self.fake_driver.is_alive.return_value = False
#
#        self.assertEqual(
#            self.instance_mgr.update_state(self.ctx),
#            states.ERROR,
#        )
#        self.fake_driver.is_alive.assert_has_calls([
#            mock.call(self.INSTANCE_INFO.management_address),
#            mock.call(self.INSTANCE_INFO.management_address),
#            mock.call(self.INSTANCE_INFO.management_address),
#        ])
#
#    @mock.patch('time.sleep')
#    def test_boot_timeout_error_no_last_boot(self, sleep):
#        self.instance_mgr.state = states.ERROR
#        self.instance_mgr.last_boot = None
#        self.update_state_p.stop()
#        self.fake_driver.is_alive.return_value = False
#
#        self.assertEqual(
#            self.instance_mgr.update_state(self.ctx),
#            states.ERROR,
#        )
#        self.fake_driver.is_alive.assert_has_calls([
#            mock.call(self.INSTANCE_INFO.management_address),
#            mock.call(self.INSTANCE_INFO.management_address),
#            mock.call(self.INSTANCE_INFO.management_address),
#        ])
#
#    @mock.patch('time.sleep')
#    def test_boot_timeout(self, sleep):
#        self.fake_driver.get_state.return_value = states.DOWN
#
#        self.instance_mgr.instances.validate_ports.return_value = \
#            ([mock.Mock()], [])  # (has_ports, no_ports)
#
#        self.instance_mgr.instances.are_alive.return_value = \
#            ([], [mock.Mock()])  # (alive, dead)
#
#        self.update_state_p.stop()
#        self.fake_driver.is_alive.return_value = False
#        self.assertEqual(self.instance_mgr.update_state(self.ctx),
#                         states.DOWN)
#        self.assertTrue(self.instance_mgr.instances.are_alive.called)
#
    def test_update_state_gone(self):
        self.update_state_p.stop()
        self.fake_driver.get_state.return_value = states.GONE
        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.GONE
        )

    def test_update_state_down_no_backing_instances(self):
        self.update_state_p.stop()
        self.fake_driver.get_state.return_value = states.UP
        self.instance_mgr.instances.__nonzero__.return_value = False
        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.DOWN
        )
        self.assertEqual(
            self.instance_mgr.state,
            states.DOWN
        )

    def test_update_state_degraded(self):
        self.update_state_p.stop()
        self.fake_driver.get_state.return_value = states.UP
        self.instance_mgr.instances.cluster_degraded = True
        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.DEGRADED
        )
        self.assertEqual(
            self.instance_mgr.state,
            states.DEGRADED
        )

    def test_update_state_booting(self):
        self.update_state_p.stop()
        self.fake_driver.get_state.return_value = states.UP
        self.instance_mgr.instances.validate_ports.return_value = \
            ([], [mock.Mock()])  # (has_ports, no_ports)
        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.BOOTING
        )

    def test_update_state_down_all_instances_dead(self):
        self.update_state_p.stop()
        self.instance_mgr.state = states.CONFIGURED
        self.instance_mgr.instances.validate_ports.return_value = \
            ([mock.Mock()], [])  # (has_ports, no_ports)
        self.instance_mgr.instances.are_alive.return_value = \
            ([], [mock.Mock()])  # (alive, dead)

        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.DOWN
        )

    def test_update_state_degraded_some_instances_dead(self):
        self.update_state_p.stop()
        self.instance_mgr.state = states.CONFIGURED
        self.instance_mgr.instances.validate_ports.return_value = \
            ([mock.Mock()], [])  # (has_ports, no_ports)
        self.instance_mgr.instances.are_alive.return_value = \
            ([mock.Mock()], [mock.Mock()])  # (alive, dead)

        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.DEGRADED
        )

    def test_update_state_up(self):
        self.update_state_p.stop()
        self.instance_mgr.state = states.BOOTING
        self.instance_mgr.instances.validate_ports.return_value = \
            ([mock.Mock()], [])  # (has_ports, no_ports)
        self.instance_mgr.instances.are_alive.return_value = \
            ([mock.Mock()], [])  # (alive, dead)

        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.UP
        )

    def test_update_state_configured(self):
        self.update_state_p.stop()
        self.instance_mgr.log = mock.Mock(
            info=mock.Mock())

        self.instance_mgr.state = states.CONFIGURED
        self.instance_mgr.instances.validate_ports.return_value = \
            ([mock.Mock()], [])  # (has_ports, no_ports)
        self.instance_mgr.instances.are_alive.return_value = \
            ([mock.Mock(booting=False)], [])  # (alive, dead)

        self.assertEqual(
            self.instance_mgr.update_state(self.ctx),
            states.CONFIGURED
        )

        self.instance_mgr.update_state(self.ctx),
        self.instance_mgr.update_state(self.ctx),
        self.instance_mgr.update_state(self.ctx),
        # ensure the boot was logged only once
        self.assertEqual(len(self.instance_mgr.log.info.call_args_list), 1)

#    @mock.patch('time.sleep')
#    def test_update_state_is_down(self, sleep):
#        self.update_state_p.stop()
#        self.fake_driver.is_alive.return_value = False
#
#        self.assertEqual(self.instance_mgr.update_state(self.ctx),
#                         states.DOWN)
#        self.fake_driver.is_alive.assert_has_calls([
#            mock.call(self.INSTANCE_INFO.management_address),
#            mock.call(self.INSTANCE_INFO.management_address),
#            mock.call(self.INSTANCE_INFO.management_address),
#        ])
#
#
#    @mock.patch('time.sleep')
#    def test_update_state_retry_delay(self, sleep):
#        self.update_state_p.stop()
#        self.fake_driver.is_alive.side_effect = [False, False, True]
#        max_retries = 5
#        self.conf.max_retries = max_retries
#        self.instance_mgr.update_state(self.ctx, silent=False)
#        self.assertEqual(sleep.call_count, 2)
#
    @mock.patch('time.sleep')
    def test_boot_success(self, sleep):
        self.next_state = states.UP
        self.instance_mgr.boot(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.BOOTING)
        self.instance_mgr.instances.create.assert_called_with(
            self.ctx, self.fake_driver)
        self.assertEqual(1, self.instance_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_instance_deleted(self, sleep):
        self.instance_mgr.instances.__nonzero__.return_value = False
        self.instance_mgr.boot(self.ctx)
        # a deleted VM should reset the vm mgr state and not as a failed
        # attempt
        self.assertEqual(self.instance_mgr.attempts, 0)

#    @mock.patch('time.sleep')
#    def test_boot_fail(self, sleep):
#        self.next_state = states.DOWN
#        self.instance_mgr.boot(self.ctx)
#        self.assertEqual(self.instance_mgr.state, states.BOOTING)
#        self.instance_mgr.instances.create.assert_called_with(
#            self.ctx, self.fake_driver)
#        self.assertEqual(1, self.instance_mgr.attempts)
#
    @mock.patch('time.sleep')
    def test_boot_exception(self, sleep):
        self.instance_mgr.instances.create.side_effect = RuntimeError
        self.instance_mgr.boot(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.DOWN)
        self.instance_mgr.instances.create.assert_called_with(
            self.ctx, self.fake_driver)
        self.assertEqual(1, self.instance_mgr.attempts)
#
#    @mock.patch('time.sleep')
#    def test_boot_with_port_cleanup(self, sleep):
#        self.next_state = states.UP
#
#        management_port = mock.Mock(id='mgmt', device_id='INSTANCE1')
#        external_port = mock.Mock(id='ext', device_id='INSTANCE1')
#        internal_port = mock.Mock(id='int', device_id='INSTANCE1')
#
#        rtr = mock.sentinel.router
#        instance = mock.sentinel.instance
#        self.ctx.neutron.get_router_detail.return_value = rtr
#        self.ctx.nova_client.boot_instance.side_effect = RuntimeError
#        rtr.id = 'ROUTER1'
#        instance.id = 'INSTANCE1'
#        rtr.management_port = management_port
#        rtr.external_port = external_port
#        rtr.ports = mock.MagicMock()
#        rtr.ports.__iter__.return_value = [management_port, external_port,
#                                           internal_port]
#        self.instance_mgr.boot(self.ctx)
#        self.ctx.nova_client.boot_instance.assert_called_once_with(
#            resource_type=self.fake_driver.RESOURCE_NAME,
#            prev_instance_info=self.INSTANCE_INFO,
#            name=self.fake_driver.name,
#            image_uuid=self.fake_driver.image_uuid,
#            flavor=self.fake_driver.flavor,
#            make_ports_callback='fake_ports_callback')
#        self.instance_mgr.resource.delete_ports.assert_called_once_with(
#            self.ctx)
#

    def test_stop_success(self):
        self.instance_mgr.state = states.UP
        instance = instance_info()
        self.set_instances_container_mocks(
            instances=[instance],
            mocks=[
                ('destroy', mock.Mock()),
                ('update_ports', mock.Mock())])

        self.instance_mgr.stop(self.ctx)
        self.instance_mgr.instances.destroy.assert_called_with(self.ctx)
        self.instance_mgr.resource.delete_ports.assert_called_once_with(
            self.ctx)
        self.assertEqual(self.instance_mgr.state, states.DOWN)

    def test_stop_fail(self):
        self.instance_mgr.state = states.UP
        self.set_instances_container_mocks(
            instances=[instance_info()],
            mocks=[
                ('destroy', mock.Mock()),
                ('update_ports', mock.Mock())])
        self.instance_mgr.instances.destroy.side_effect = Exception
        self.instance_mgr.stop(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.UP)
        self.fake_driver.delete_ports.assert_called_with(self.ctx)

    def test_stop_router_already_deleted_from_neutron(self):
        self.instance_mgr.state = states.GONE
        instance = instance_info()
        self.set_instances_container_mocks(
            instances=[instance],
            mocks=[
                ('destroy', mock.Mock()),
                ('update_ports', mock.Mock())])

        self.instance_mgr.stop(self.ctx)
        self.instance_mgr.instances.destroy.assert_called_with(self.ctx)
        self.instance_mgr.resource.delete_ports.assert_called_once_with(
            self.ctx)
        self.assertEqual(self.instance_mgr.state, states.GONE)

    def test_stop_no_inst_router_already_deleted_from_neutron(self):
        self.instance_mgr.state = states.GONE
        self.set_instances_container_mocks(
            instances=[],
            mocks=[
                ('destroy', mock.Mock()),
                ('update_ports', mock.Mock())])
        self.instance_mgr.stop(self.ctx)
        self.fake_driver.delete_ports.assert_called_with(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.GONE)

    def test_stop_instance_already_deleted_from_nova(self):
        self.instance_mgr.state = states.RESTART
        self.set_instances_container_mocks(
            instances=[],
            mocks=[
                ('destroy', mock.Mock()),
                ('update_ports', mock.Mock())])

        self.instance_mgr.stop(self.ctx)
        self.fake_driver.delete_ports.assert_called_with(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.DOWN)

    def test_configure_mismatched_interfaces(self):
        self.instance_mgr.instances.verify_interfaces.return_value = False
        self.assertEqual(
            self.instance_mgr.configure(self.ctx),
            states.REPLUG,
        )

    def test_configure_gone(self):
        self.fake_driver.get_state.return_value = states.GONE
        self.assertEqual(
            self.instance_mgr.configure(self.ctx), states.GONE)

    def test_configure(self):
        self.instance_mgr.instances.verify_interfaces.return_value = True
        self.instance_mgr.instances.configure.return_value = states.RESTART
        self.assertEqual(
            self.instance_mgr.configure(self.ctx),
            states.RESTART,
        )
        self.instance_mgr.instances.verify_interfaces.assert_called_with(
            self.fake_driver.ports
        )
        self.instance_mgr.instances.configure.assert_called_with(self.ctx)

    @mock.patch.object(instance_manager.InstanceManager,
                       '_wait_for_interface_hotplug')
    def test_replug_add_new_port_success(self, wait_for_hotplug):
        self.instance_mgr.state = states.REPLUG
        instance = instance_info()
        get_interfaces = mock.Mock(
            return_value={
                instance: [
                    {'lladdr': fake_mgt_port.mac_address},
                    {'lladdr': fake_ext_port.mac_address},
                    {'lladdr': fake_int_port.mac_address}]
            }
        )
        self.set_instances_container_mocks(
            instances=[instance], mocks=[('get_interfaces', get_interfaces)])

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)

        fake_new_port = fake_add_port
        self.fake_driver.ports.append(fake_new_port)
        self.ctx.neutron.create_vrrp_port.return_value = fake_new_port

        self.fake_driver.get_interfaces.return_value = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
            {'lladdr': fake_int_port.mac_address},
            {'lladdr': fake_new_port.mac_address},
        ]

        wait_for_hotplug.return_value = True
        self.instance_mgr.replug(self.ctx)

        self.ctx.neutron.create_vrrp_port.assert_called_with(
            self.fake_driver.id, 'additional-net'
        )
        self.assertEqual(self.instance_mgr.state, states.REPLUG)
        fake_instance.interface_attach.assert_called_once_with(
            fake_new_port.id, None, None
        )
        self.assertIn(fake_new_port, instance.ports)

    def test_replug_add_new_port_failure(self):
        self.instance_mgr.state = states.REPLUG
        instance = instance_info()
        get_interfaces = mock.Mock(
            return_value={
                instance: [
                    {'lladdr': fake_mgt_port.mac_address},
                    {'lladdr': fake_ext_port.mac_address},
                    {'lladdr': fake_int_port.mac_address}]
            }
        )

        self.set_instances_container_mocks(
            instances=[instance],
            mocks=[('get_interfaces', get_interfaces)]
        )
        self.fake_driver.get_interfaces.return_value = [
            {'lladdr': fake_mgt_port.mac_address},
            {'lladdr': fake_ext_port.mac_address},
            {'lladdr': fake_int_port.mac_address}
        ]
        fake_instance = mock.MagicMock()
        fake_instance.interface_attach = mock.Mock(
            side_effect=Exception,
        )
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)

        fake_new_port = fake_add_port
        self.fake_driver.ports.append(fake_new_port)
        self.ctx.neutron.create_vrrp_port.return_value = fake_new_port
        self.instance_mgr.replug(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.RESTART)

        fake_instance.interface_attach.assert_called_once_with(
            fake_new_port.id, None, None)

    @mock.patch.object(instance_manager.InstanceManager,
                       '_wait_for_interface_hotplug')
    def test_replug_add_new_port_failed_degraded(self, wait_for_hotplug):
        self.conf.hotplug_timeout = 2
        self.instance_mgr.state = states.REPLUG
        instance_1 = instance_info()
        instance_2 = instance_info()
        get_interfaces = mock.Mock(
            return_value={
                instance_1: [
                    {'lladdr': fake_mgt_port.mac_address},
                    {'lladdr': fake_ext_port.mac_address},
                    {'lladdr': fake_int_port.mac_address}],
                instance_2: [
                    {'lladdr': fake_mgt_port.mac_address},
                    {'lladdr': fake_ext_port.mac_address},
                    {'lladdr': fake_int_port.mac_address}]
            }
        )

        self.set_instances_container_mocks(
            instances=[instance_1, instance_2],
            mocks=[('get_interfaces', get_interfaces)])
        self.instance_mgr.instances.update({
            i.id_: i for i in [instance_1, instance_2]
        })

        instances = []
        for i in range(2):
            fake_instance = mock.MagicMock()
            fake_instance.interface_attach = mock.Mock()
            instances.append(fake_instance)

        instances[1].interface_attach.side_effect = Exception
        self.ctx.nova_client.get_instance_by_id.side_effect = instances

        fake_new_port = fake_add_port
        self.fake_driver.ports.append(fake_new_port)
        self.ctx.neutron.create_vrrp_port.return_value = fake_new_port

        wait_for_hotplug.return_value = True
        self.instance_mgr.replug(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.DEGRADED)

        for instance in instances:
            instance.interface_attach.assert_called_with(
                fake_new_port.id, None, None)
        self.assertNotIn(instances[1], self.instance_mgr.instances.values())

    @mock.patch.object(instance_manager.InstanceManager,
                       '_wait_for_interface_hotplug')
    def test_replug_add_new_port_hotplug_failed_degraded(self,
                                                         wait_for_hotplug):
        self.instance_mgr.state = states.REPLUG
        instance_1 = instance_info()
        instance_2 = instance_info()
        get_interfaces = mock.Mock(
            return_value={
                instance_1: [
                    {'lladdr': fake_mgt_port.mac_address},
                    {'lladdr': fake_ext_port.mac_address},
                    {'lladdr': fake_int_port.mac_address}],
                instance_2: [
                    {'lladdr': fake_mgt_port.mac_address},
                    {'lladdr': fake_ext_port.mac_address},
                    {'lladdr': fake_int_port.mac_address}]
            }
        )

        self.set_instances_container_mocks(
            instances=[instance_1, instance_2],
            mocks=[('get_interfaces', get_interfaces)])

        fake_new_port = fake_add_port

        instances = []
        for i in range(2):
            fake_instance = mock.MagicMock()
            fake_instance.interface_attach = mock.Mock()
            instances.append(fake_instance)
        self.ctx.nova_client.get_instance_by_id.side_effect = instances

        fake_new_port = fake_add_port
        self.fake_driver.ports.append(fake_new_port)
        self.ctx.neutron.create_vrrp_port.return_value = fake_new_port

        # the second instance fails to hotplug
        wait_for_hotplug.side_effect = [True, False]

        self.instance_mgr.replug(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.DEGRADED)

        for instance in instances:
            instance.interface_attach.assert_called_with(
                fake_new_port.id, None, None)
        self.assertNotIn(instances[1], self.instance_mgr.instances.values())

    @mock.patch.object(instance_manager.InstanceManager,
                       '_wait_for_interface_hotplug')
    def test_replug_remove_port_success(self, wait_for_hotplug):
        self.instance_mgr.state = states.REPLUG

        self.fake_driver.ports = [fake_ext_port, fake_int_port]

        instance_1 = instance_info()
        instance_1.ports.append(fake_add_port)

        get_interfaces = mock.Mock(
            return_value={
                # Instance contains an extra port, it will be removed
                instance_1: [
                    {'lladdr': fake_mgt_port.mac_address},
                    {'lladdr': fake_ext_port.mac_address},
                    {'lladdr': fake_int_port.mac_address},
                    {'lladdr': fake_add_port.mac_address},
                ],
            }
        )
        self.set_instances_container_mocks(
            instances=[instance_1],
            mocks=[('get_interfaces', get_interfaces)])

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)

        wait_for_hotplug.return_value = True
        self.instance_mgr.replug(self.ctx)
        self.assertEqual(self.instance_mgr.state, states.REPLUG)
        fake_instance.interface_detach.assert_called_once_with(
            fake_add_port.id)
        self.assertNotIn(fake_add_port, instance_1.ports)

    def test_replug_remove_port_failure(self):
        self.instance_mgr.state = states.REPLUG

        self.fake_driver.ports = [fake_ext_port, fake_int_port]

        instance_1 = instance_info()
        instance_1.ports.append(fake_add_port)

        get_interfaces = mock.Mock(
            return_value={
                # Instance contains an extra port, it will be removed
                instance_1: [
                    {'lladdr': fake_mgt_port.mac_address},
                    {'lladdr': fake_ext_port.mac_address},
                    {'lladdr': fake_int_port.mac_address},
                    {'lladdr': fake_add_port.mac_address}],
            }
        )
        self.set_instances_container_mocks(
            instances=[instance_1],
            mocks=[('get_interfaces', get_interfaces)])

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)
        fake_instance.interface_detach.side_effect = Exception

        self.instance_mgr.replug(self.ctx)
        self.assertEqual(self.instance_mgr.state,
                         states.RESTART)
        fake_instance.interface_detach.assert_called_once_with(
            fake_add_port.id
        )

    @mock.patch.object(instance_manager.InstanceManager,
                       '_wait_for_interface_hotplug')
    def test_replug_remove_port_hotplug_failed(self, wait_for_hotplug):
        self.instance_mgr.state = states.REPLUG

        self.fake_driver.ports = [fake_ext_port, fake_int_port]

        instance_1 = instance_info()
        instance_1.ports.append(fake_add_port)

        get_interfaces = mock.Mock(
            return_value={
                # Instance contains an extra port, it will be removed
                instance_1: [
                    {'lladdr': fake_mgt_port.mac_address},
                    {'lladdr': fake_ext_port.mac_address},
                    {'lladdr': fake_int_port.mac_address},
                    {'lladdr': fake_add_port.mac_address}
                ],
            }
        )
        self.set_instances_container_mocks(
            instances=[instance_1],
            mocks=[('get_interfaces', get_interfaces)])

        fake_instance = mock.MagicMock()
        self.ctx.nova_client.get_instance_by_id = mock.Mock(
            return_value=fake_instance)

        wait_for_hotplug.return_value = False
        self.instance_mgr.replug(self.ctx)
        self.assertEqual(self.instance_mgr.state,
                         states.RESTART)
        fake_instance.interface_detach.assert_called_once_with(
            fake_add_port.id
        )

    def test_wait_for_interface_hotplug_true(self):
        instance = instance_info()
        self.fake_driver.get_interfaces.side_effect = [
            [
                {'lladdr': fake_mgt_port.mac_address},
                {'lladdr': fake_ext_port.mac_address},
            ],
            [
                {'lladdr': fake_mgt_port.mac_address},
                {'lladdr': fake_ext_port.mac_address},
            ],
            [
                {'lladdr': fake_mgt_port.mac_address},
                {'lladdr': fake_ext_port.mac_address},
                {'lladdr': fake_int_port.mac_address},
            ],
        ]
        self.assertEqual(
            self.instance_mgr._wait_for_interface_hotplug(instance), True)
        self.assertEqual(
            len(self.fake_driver.get_interfaces.call_args_list), 3)

    def test_wait_for_interface_hotplug_false(self):
        self.conf.hotplug_timeout = 5
        instance = instance_info()
        self.fake_driver.get_interfaces.side_effect = [
            [
                {'lladdr': fake_mgt_port.mac_address},
                {'lladdr': fake_ext_port.mac_address},
            ]
            for i in six.moves.range(5)]
        self.assertEqual(
            self.instance_mgr._wait_for_interface_hotplug(instance), False)
        self.assertEqual(
            len(self.fake_driver.get_interfaces.call_args_list), 4)

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
        self.instance_mgr.instances.create.assert_called_with(
            self.ctx, self.fake_driver)

    def test_error_cooldown(self):
        self.config(error_state_cooldown=30)
        self.assertIsNone(self.instance_mgr.last_error)
        self.assertFalse(self.instance_mgr.error_cooldown)

        self.instance_mgr.state = states.ERROR
        self.instance_mgr.last_error = datetime.utcnow() - timedelta(seconds=1)
        self.assertTrue(self.instance_mgr.error_cooldown)

        self.instance_mgr.last_error = datetime.utcnow() - timedelta(minutes=5)
        self.assertFalse(self.instance_mgr.error_cooldown)

    def test_ensure_cache(self):
        self.set_instances_container_mocks(mocks=[
            ('update_ports', mock.Mock())
        ])
        self.instance_mgr.instances['fake_instance_id1'] = 'stale_instance1'
        self.instance_mgr.instances['fake_instance_id2'] = 'stale_instance2'

        fake_inst_1 = mock.Mock(id_='fake_instance_id1')
        fake_inst_2 = mock.Mock(id_='fake_instance_id2')

        self.ctx.nova_client.get_instances_for_obj.return_value = [
            fake_inst_1, fake_inst_2]

        def ensured_cache(self, ctx):
            pass

        wrapped = instance_manager.ensure_cache(ensured_cache)
        wrapped(self.instance_mgr, self.ctx)
        exp_updated_instances = {
            'fake_instance_id1': fake_inst_1,
            'fake_instance_id2': fake_inst_2,
        }
        self.assertEqual(
            self.instance_mgr.instances, exp_updated_instances)
        self.instance_mgr.instances.update_ports.assert_called_with(self.ctx)


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
