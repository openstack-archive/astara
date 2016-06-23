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

import collections
import mock
import six
import uuid

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


def instance_info(mgt_port=fake_mgt_port, name=None):
        if not name:
            name = 'ak-router-' + str(uuid.uuid4())

        return nova.InstanceInfo(
            instance_id=str(uuid.uuid4()),
            name=name,
            management_port=mgt_port,
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
        self.neutron.api_client = mock.Mock()
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

            def refresh(self, worker_context):
                pass

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

    def test_update_state_gone(self):
        self.update_state_p.stop()
        self.fake_driver.get_state.return_value = states.GONE
        self.assertEqual(
            states.GONE,
            self.instance_mgr.update_state(self.ctx)
        )

    def test_update_state_down_no_backing_instances(self):
        self.update_state_p.stop()
        self.fake_driver.get_state.return_value = states.UP
        self.instance_mgr.instances.__nonzero__.return_value = False
        self.assertEqual(
            states.DOWN,
            self.instance_mgr.update_state(self.ctx)
        )
        self.assertEqual(
            states.DOWN,
            self.instance_mgr.state
        )

    def test_update_state_degraded(self):
        self.update_state_p.stop()
        self.fake_driver.get_state.return_value = states.UP
        self.instance_mgr.instances.cluster_degraded = True
        self.assertEqual(
            states.DEGRADED,
            self.instance_mgr.update_state(self.ctx)
        )
        self.assertEqual(
            states.DEGRADED,
            self.instance_mgr.state
        )

    def test_update_state_booting(self):
        self.update_state_p.stop()
        self.fake_driver.get_state.return_value = states.UP
        self.instance_mgr.instances.validate_ports.return_value = \
            ([], [mock.Mock()])  # (has_ports, no_ports)
        self.assertEqual(
            states.BOOTING,
            self.instance_mgr.update_state(self.ctx)
        )

    def test_update_state_down_all_instances_dead(self):
        self.update_state_p.stop()
        self.instance_mgr.state = states.CONFIGURED
        self.instance_mgr.instances.validate_ports.return_value = \
            ([mock.Mock()], [])  # (has_ports, no_ports)
        self.instance_mgr.instances.are_alive.return_value = \
            ([], [mock.Mock()])  # (alive, dead)

        self.assertEqual(
            states.DOWN,
            self.instance_mgr.update_state(self.ctx)
        )

    def test_update_state_degraded_some_instances_dead(self):
        self.update_state_p.stop()
        self.instance_mgr.state = states.CONFIGURED
        self.instance_mgr.instances.validate_ports.return_value = \
            ([mock.Mock()], [])  # (has_ports, no_ports)
        self.instance_mgr.instances.are_alive.return_value = \
            ([mock.Mock()], [mock.Mock()])  # (alive, dead)

        self.assertEqual(
            states.DEGRADED,
            self.instance_mgr.update_state(self.ctx)
        )

    def test_update_state_up(self):
        self.update_state_p.stop()
        self.instance_mgr.state = states.BOOTING
        self.instance_mgr.instances.validate_ports.return_value = \
            ([mock.Mock()], [])  # (has_ports, no_ports)
        self.instance_mgr.instances.are_alive.return_value = \
            ([mock.Mock()], [])  # (alive, dead)

        self.assertEqual(
            states.UP,
            self.instance_mgr.update_state(self.ctx)
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
            states.CONFIGURED,
            self.instance_mgr.update_state(self.ctx)
        )

        self.instance_mgr.update_state(self.ctx),
        self.instance_mgr.update_state(self.ctx),
        self.instance_mgr.update_state(self.ctx),
        # ensure the boot was logged only once
        self.assertEqual(1, len(self.instance_mgr.log.info.call_args_list))

    @mock.patch('time.sleep')
    def test_boot_success(self, sleep):
        self.next_state = states.UP
        self.instance_mgr.boot(self.ctx)
        self.assertEqual(states.BOOTING, self.instance_mgr.state)
        self.instance_mgr.instances.create.assert_called_with(
            self.ctx)
        self.assertEqual(1, self.instance_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_instance_deleted(self, sleep):
        self.instance_mgr.instances.__nonzero__.return_value = False
        self.instance_mgr.boot(self.ctx)
        # a deleted VM should reset the vm mgr state and not as a failed
        # attempt
        self.assertEqual(0, self.instance_mgr.attempts)

    @mock.patch('time.sleep')
    def test_boot_exception(self, sleep):
        self.instance_mgr.instances.create.side_effect = RuntimeError
        self.instance_mgr.boot(self.ctx)
        self.assertEqual(states.DOWN, self.instance_mgr.state)
        self.instance_mgr.instances.create.assert_called_with(
            self.ctx)
        self.assertEqual(1, self.instance_mgr.attempts)

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
        self.assertEqual(states.DOWN, self.instance_mgr.state)

    def test_stop_fail(self):
        self.instance_mgr.state = states.UP
        self.set_instances_container_mocks(
            instances=[instance_info()],
            mocks=[
                ('destroy', mock.Mock()),
                ('update_ports', mock.Mock())])
        self.instance_mgr.instances.destroy.side_effect = Exception
        self.instance_mgr.stop(self.ctx)
        self.assertEqual(states.UP, self.instance_mgr.state)
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
        self.assertEqual(states.GONE, self.instance_mgr.state)

    def test_stop_no_inst_router_already_deleted_from_neutron(self):
        self.instance_mgr.state = states.GONE
        self.set_instances_container_mocks(
            instances=[],
            mocks=[
                ('destroy', mock.Mock()),
                ('update_ports', mock.Mock())])
        self.instance_mgr.stop(self.ctx)
        self.fake_driver.delete_ports.assert_called_with(self.ctx)
        self.assertEqual(states.GONE, self.instance_mgr.state)

    def test_stop_instance_already_deleted_from_nova(self):
        self.instance_mgr.state = states.RESTART
        self.set_instances_container_mocks(
            instances=[],
            mocks=[
                ('destroy', mock.Mock()),
                ('update_ports', mock.Mock())])

        self.instance_mgr.stop(self.ctx)
        self.fake_driver.delete_ports.assert_called_with(self.ctx)
        self.assertEqual(states.DOWN, self.instance_mgr.state)

    def test_configure_mismatched_interfaces(self):
        self.instance_mgr.instances.verify_interfaces.return_value = False
        self.assertEqual(
            states.REPLUG,
            self.instance_mgr.configure(self.ctx)
        )

    def test_configure_gone(self):
        self.fake_driver.get_state.return_value = states.GONE
        self.assertEqual(
            states.GONE, self.instance_mgr.configure(self.ctx))

    def test_configure(self):
        self.instance_mgr.instances.verify_interfaces.return_value = True
        self.instance_mgr.instances.configure.return_value = states.RESTART
        self.assertEqual(
            states.RESTART,
            self.instance_mgr.configure(self.ctx)
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
        self.assertEqual(states.REPLUG, self.instance_mgr.state)
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
        self.assertEqual(states.RESTART, self.instance_mgr.state)

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
        self.assertEqual(states.DEGRADED, self.instance_mgr.state)

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
        self.assertEqual(states.DEGRADED, self.instance_mgr.state)

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
        self.assertEqual(states.REPLUG, self.instance_mgr.state)
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
        self.assertEqual(states.RESTART,
                         self.instance_mgr.state)
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
        self.assertEqual(states.RESTART,
                         self.instance_mgr.state)
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
            True, self.instance_mgr._wait_for_interface_hotplug(instance))
        self.assertEqual(
            3, len(self.fake_driver.get_interfaces.call_args_list))

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
            False, self.instance_mgr._wait_for_interface_hotplug(instance))
        self.assertEqual(
            4, len(self.fake_driver.get_interfaces.call_args_list))

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
        self.assertEqual(states.BOOTING, self.instance_mgr.state)
        self.instance_mgr.instances.create.assert_called_with(self.ctx)

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
            exp_updated_instances, self.instance_mgr.instances)
        self.instance_mgr.instances.update_ports.assert_called_with(self.ctx)


class TestBootAttemptCounter(base.RugTestBase):
    def setUp(self):
        super(TestBootAttemptCounter, self).setUp()
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


class TestInstanceGroupManager(base.RugTestBase):
    def setUp(self):
        super(TestInstanceGroupManager, self).setUp()
        self.ctx = fakes.fake_worker_context()
        self.fake_driver = fakes.fake_driver()
        self.group_mgr = instance_manager.InstanceGroupManager(
            log=mock.Mock(), resource=self.fake_driver)
        name = 'ak-resource-' + str(uuid.uuid4())
        self.instance_1 = instance_info(mgt_port=fake_mgt_port,
                                        name=name + '_0')
        self.instance_2 = instance_info(mgt_port=fake_add_port,
                                        name=name + '_1')
        self.instances = [self.instance_1, self.instance_2]
        [self.group_mgr.add_instance(i) for i in self.instances]

    def test_validate_ports(self):
        self.instance_2.management_port = None
        has_ports, no_ports = self.group_mgr.validate_ports()
        self.assertIn(self.instance_1, has_ports)
        self.assertIn(self.instance_2, no_ports)

    def test_are_alive_all_alive(self):
        self.fake_driver.is_alive.side_effect = [
            False, False, True, False, True]
        alive, dead = self.group_mgr.are_alive()
        self.assertEqual(sorted(self.instances), sorted(alive))

    def test_are_alive_all_dead(self):
        self.fake_driver.is_alive.return_value = False
        alive, dead = self.group_mgr.are_alive()
        self.assertEqual(sorted(self.instances), sorted(dead))
        self.assertEqual([], alive)

    def test_are_alive_some_dead(self):
        self.group_mgr = instance_manager.InstanceGroupManager(
            log=mock.Mock(), resource=self.fake_driver)
        self.instance_1 = instance_info(mgt_port=fake_mgt_port)
        self.instance_2 = instance_info(mgt_port=fake_add_port)
        instances = [self.instance_1, self.instance_2]
        [self.group_mgr.add_instance(i) for i in instances]

        def fake_is_alive(mgt_addr, i1=self.instance_1, i2=self.instance_2):
            # tag instance 2 as dead
            if mgt_addr == fake_add_port.fixed_ips[0].ip_address:
                return False
            else:
                return True
        [self.group_mgr.add_instance(i) for i in instances]
        self.fake_driver.is_alive = fake_is_alive
        alive, dead = self.group_mgr.are_alive()
        self.assertEqual([self.instance_2], dead)
        self.assertEqual([self.instance_1], alive)

    def test_update_ports(self):
        self.ctx.neutron.get_ports_for_instance.side_effect = [
            ('instance1_mgt_port', ['instance1_inst_port']),
            ('instance2_mgt_port', ['instance2_inst_port']),
        ]
        self.group_mgr.update_ports(self.ctx)
        self.assertEqual('instance1_mgt_port', self.instance_1.management_port)
        self.assertEqual(['instance1_inst_port'], self.instance_1.ports)
        self.assertEqual('instance2_mgt_port', self.instance_2.management_port)
        self.assertEqual(['instance2_inst_port'], self.instance_2.ports)

    def test_get_interfaces(self):
        self.fake_driver.get_interfaces.side_effect = [
            ['instance1_interfaces'],
            ['instance2_interfaces'],
        ]
        self.group_mgr._alive = [i.id_ for i in self.instances]
        interfaces_dict = self.group_mgr.get_interfaces()
        self.assertIn(
            (self.instance_1, ['instance1_interfaces']),
            interfaces_dict.items())
        self.assertIn(
            (self.instance_2, ['instance2_interfaces']),
            interfaces_dict.items())

    def test_get_interfaces_skip_dead(self):
        self.fake_driver.get_interfaces.side_effect = [
            ['instance1_interfaces'],
            ['instance2_interfaces'],
        ]
        self.group_mgr._alive = [self.instance_1.id_]
        interfaces_dict = self.group_mgr.get_interfaces()
        self.assertIn(
            (self.instance_1, ['instance1_interfaces']),
            interfaces_dict.items())
        self.assertNotIn(
            (self.instance_2, ['instance2_interfaces']),
            interfaces_dict.items())

    @mock.patch('astara.instance_manager.InstanceGroupManager.get_interfaces')
    def test_verify_interfaces_true(self, fake_get_interfaces):
        fake_get_interfaces.return_value = {
            self.instance_1: [
                {'lladdr': p.mac_address}
                for p in self.instance_1.ports +
                [self.instance_1.management_port]
            ],
            self.instance_2: [
                {'lladdr': p.mac_address}
                for p in self.instance_2.ports +
                [self.instance_2.management_port]
            ]
        }

        ports = [fake_ext_port, fake_int_port]
        self.assertTrue(self.group_mgr.verify_interfaces(ports))

    @mock.patch('astara.instance_manager.InstanceGroupManager.get_interfaces')
    def test_verify_interfaces_false_missing_inst_port(self,
                                                       fake_get_interfaces):
        fake_get_interfaces.return_value = {
            self.instance_1: [
                {'lladdr': p.mac_address}
                for p in self.instance_1.ports +
                [self.instance_1.management_port]
            ],
            self.instance_2: [
                {'lladdr': p.mac_address}
                for p in self.instance_2.ports +
                [self.instance_2.management_port]
            ]
        }

        ports = [fake_ext_port, fake_int_port, fake_add_port]
        self.assertFalse(self.group_mgr.verify_interfaces(ports))

    @mock.patch('astara.instance_manager.InstanceGroupManager.get_interfaces')
    def test_verify_interfaces_false_missing_macs(self, fake_get_interfaces):
        fake_get_interfaces.return_value = {
            self.instance_1: [
                {'lladdr': p.mac_address}
                for p in self.instance_1.ports
            ],
            self.instance_2: [
                {'lladdr': p.mac_address}
                for p in self.instance_2.ports]
        }

        ports = [fake_ext_port, fake_int_port]
        self.assertFalse(self.group_mgr.verify_interfaces(ports))

    def test__update_config_success(self):
        self.fake_driver.update_config.side_effect = [
            Exception, Exception, True]
        self.assertTrue(self.group_mgr._update_config(self.instance_1, {}))
        self.fake_driver.update_config.assert_called_with(
            self.instance_1.management_address, {})

    def test__update_config_fail(self):
        self.fake_driver.update_config.side_effect = Exception
        self.assertFalse(self.group_mgr._update_config(self.instance_1, {}))
        self.fake_driver.update_config.assert_called_with(
            self.instance_1.management_address, {})

    def test__ha_config(self):
        instance_1_ha_config = self.group_mgr._ha_config(self.instance_1)
        instance_2_ha_config = self.group_mgr._ha_config(self.instance_2)
        self.assertEqual(
            {
                'priority': 100,
                'peers': [self.instance_2.management_address],
            },
            instance_1_ha_config)
        self.assertEqual(
            {
                'priority': 50,
                'peers': [self.instance_1.management_address],
            },
            instance_2_ha_config)

    @mock.patch('astara.instance_manager.InstanceGroupManager._update_config')
    @mock.patch('astara.instance_manager.InstanceGroupManager._ha_config')
    @mock.patch('astara.instance_manager._generate_interface_map')
    @mock.patch('astara.instance_manager.InstanceGroupManager.get_interfaces')
    def test_configure_success(self, fake_get_interfaces, fake_gen_iface_map,
                               fake_ha_config, fake_update_config):
        fake_ha_config.return_value = {'fake_ha_config': 'peers'}
        self.fake_driver.is_ha = True
        self.fake_driver.build_config.side_effect = [
            {'instance_1_config': 'config'},
            {'instance_2_config': 'config'},
        ]
        fake_get_interfaces.return_value = collections.OrderedDict([
            (self.instance_1, [
             {'lladdr': p.mac_address} for p in self.instance_1.ports +
             [self.instance_1.management_port]]),
            (self.instance_2, [
             {'lladdr': p.mac_address} for p in self.instance_2.ports +
             [self.instance_2.management_port]])
        ])

        fake_update_config.return_value = True
        self.assertEqual(states.CONFIGURED, self.group_mgr.configure(self.ctx))
        self.assertIn(
            mock.call(
                self.instance_1,
                {
                    'instance_1_config': 'config',
                    'ha_config': {'fake_ha_config': 'peers'}
                }),
            fake_update_config.call_args_list)
        self.assertIn(
            mock.call(
                self.instance_2,
                {
                    'instance_2_config': 'config',
                    'ha_config': {'fake_ha_config': 'peers'}
                }),
            fake_update_config.call_args_list)

    @mock.patch('astara.instance_manager.InstanceGroupManager._update_config')
    @mock.patch('astara.instance_manager.InstanceGroupManager._ha_config')
    @mock.patch('astara.instance_manager._generate_interface_map')
    @mock.patch('astara.instance_manager.InstanceGroupManager.get_interfaces')
    def test_configure_failed_all(self, fake_get_interfaces,
                                  fake_gen_iface_map, fake_ha_config,
                                  fake_update_config):
        fake_ha_config.return_value = {'fake_ha_config': 'peers'}
        self.fake_driver.is_ha = True
        self.fake_driver.build_config.side_effect = [
            {'instance_1_config': 'config'},
            {'instance_2_config': 'config'},
        ]
        fake_get_interfaces.return_value = collections.OrderedDict([
            (self.instance_1, [
             {'lladdr': p.mac_address} for p in self.instance_1.ports +
             [self.instance_1.management_port]]),
            (self.instance_2, [
             {'lladdr': p.mac_address} for p in self.instance_2.ports +
             [self.instance_2.management_port]])
        ])

        fake_update_config.return_value = False
        self.assertEqual(states.RESTART, self.group_mgr.configure(self.ctx))

    @mock.patch('astara.instance_manager.InstanceGroupManager._update_config')
    @mock.patch('astara.instance_manager.InstanceGroupManager._ha_config')
    @mock.patch('astara.instance_manager._generate_interface_map')
    @mock.patch('astara.instance_manager.InstanceGroupManager.get_interfaces')
    def test_configure_failed_some(self, fake_get_interfaces,
                                   fake_gen_iface_map, fake_ha_config,
                                   fake_update_config):
        fake_ha_config.return_value = {'fake_ha_config': 'peers'}
        self.fake_driver.is_ha = True
        self.fake_driver.build_config.side_effect = [
            {'instance_1_config': 'config'},
            {'instance_2_config': 'config'},
        ]
        fake_get_interfaces.return_value = collections.OrderedDict([
            (self.instance_1, [
             {'lladdr': p.mac_address} for p in self.instance_1.ports +
             [self.instance_1.management_port]]),
            (self.instance_2, [
             {'lladdr': p.mac_address} for p in self.instance_2.ports +
             [self.instance_2.management_port]])])

        fake_update_config.side_effect = [False, True]
        self.assertEqual(states.DEGRADED, self.group_mgr.configure(self.ctx))

    @mock.patch('astara.instance_manager.InstanceGroupManager._update_config')
    @mock.patch('astara.instance_manager.InstanceGroupManager._ha_config')
    @mock.patch('astara.instance_manager._generate_interface_map')
    @mock.patch('astara.instance_manager.InstanceGroupManager.get_interfaces')
    def test_configure_degraded_waiting(self, fake_get_interfaces,
                                        fake_gen_iface_map, fake_ha_config,
                                        fake_update_config):
        fake_ha_config.return_value = {'fake_ha_config': 'peers'}
        self.fake_driver.is_ha = True
        self.fake_driver.build_config.side_effect = [
            {'instance_1_config': 'config'},
            {'instance_2_config': 'config'},
        ]
        fake_get_interfaces.return_value = collections.OrderedDict([
            (self.instance_1, [
             {'lladdr': p.mac_address} for p in self.instance_1.ports +
             [self.instance_1.management_port]])
        ])

        fake_update_config.return_value = True
        self.assertEqual(states.DEGRADED, self.group_mgr.configure(self.ctx))

    def test_delete(self):
        self.group_mgr.delete(self.instance_2)
        self.assertNotIn(
            self.instance_2, self.group_mgr.instances)

    def test_refresh(self):
        self.ctx.nova_client.update_instance_info.return_value = True
        self.group_mgr.refresh(self.ctx)
        [self.assertIn(mock.call(i),
         self.ctx.nova_client.update_instance_info.call_args_list)
         for i in self.instances]
        [self.assertIn(i, self.group_mgr.instances) for i in self.instances]

    def test_refresh_instance_gone(self):
        self.ctx.nova_client.update_instance_info.side_effect = [True, None]
        self.group_mgr.refresh(self.ctx)
        [self.assertIn(mock.call(i),
         self.ctx.nova_client.update_instance_info.call_args_list)
         for i in self.instances]
        self.assertIn(self.instance_1, self.group_mgr.instances)
        self.assertNotIn(self.instance_2, self.group_mgr.instances)

    def test_destroy(self):
        self.group_mgr.destroy(self.ctx)
        self.ctx.nova_client.delete_instances_and_wait.assert_called_with(
            self.group_mgr.instances)

    def test_remove(self):
        self.group_mgr.remove(self.ctx, self.instance_1)
        self.ctx.nova_client.destroy_instance.assert_called_with(
            self.instance_1)
        self.assertNotIn(self.instance_1, self.group_mgr.instances)

    def test_next_instance_index(self):
        self.assertEqual(
            2, self.group_mgr.next_instance_index)

    def test_next_instance_index_empty(self):
        group_mgr = instance_manager.InstanceGroupManager(
            log=mock.Mock(), resource=self.fake_driver)
        self.assertEqual(
            0, group_mgr.next_instance_index)

    def test_create_all(self):
        [self.group_mgr.delete(i) for i in self.instances]
        self.ctx.nova_client.boot_instance.side_effect = [
            instance_info(name='new-instance_0'),
            instance_info(name='new-instance_1'),
        ]
        self.group_mgr.create(self.ctx)
        self.assertEqual(
            2, len(self.ctx.nova_client.boot_instance.call_args_list))

    def test_create_some(self):
        self.group_mgr.delete(self.instance_1)
        self.ctx.nova_client.boot_instance.side_effect = [
            instance_info(name='new-instance_0'),
        ]
        self.group_mgr.create(self.ctx)
        self.assertEqual(
            1, len(self.ctx.nova_client.boot_instance.call_args_list))
        self.ctx.nova_client.boot_instance.assert_called_with(
            resource_type=self.fake_driver.RESOURCE_NAME,
            prev_instance_info=None,
            name='ak-FakeDriver-fake_resource_id_2',
            image_uuid=self.fake_driver.image_uuid,
            flavor=self.fake_driver.flavor,
            make_ports_callback=self.fake_driver.make_ports(self.ctx),
        )

    def test_required_instance_count(self):
        self.fake_driver.is_ha = True
        self.assertEqual(2, self.group_mgr.required_instance_count)
        self.fake_driver.is_ha = False
        self.assertEqual(1, self.group_mgr.required_instance_count)

    def test_instance_count(self):
        self.assertEqual(2, self.group_mgr.instance_count)

    def test_cluster_degraded_false(self):
        self.assertFalse(self.group_mgr.cluster_degraded)

    def test_cluster_degraded_true(self):
        self.group_mgr.delete(self.instance_1)
        self.assertTrue(self.group_mgr.cluster_degraded)

    def test_add_instance(self):
        instance_3 = instance_info()
        self.group_mgr.add_instance(instance_3)
        self.assertIn(instance_3, self.group_mgr.instances)
