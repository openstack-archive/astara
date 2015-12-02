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


# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import unittest

import mock
from oslo_config import cfg

from akanda.rug.common.linux import interface
from akanda.rug.common.linux import ip_lib
from akanda.rug.common.linux import utils


class BaseChild(interface.LinuxInterfaceDriver):
    def plug(*args):
        pass

    def unplug(*args):
        pass


class FakeNetwork:
    id = '12345678-1234-5678-90ab-ba0987654321'


class FakeSubnet:
    cidr = '192.168.1.1/24'


class FakeAllocation:
    subnet = FakeSubnet()
    ip_address = '192.168.1.2'
    ip_version = 4


class FakePort:
    id = 'abcdef01-1234-5678-90ab-ba0987654321'
    fixed_ips = [FakeAllocation]
    device_id = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
    network = FakeNetwork()
    network_id = network.id


class TestBase(unittest.TestCase):
    def setUp(self):
        root_helper_opt = [
            cfg.StrOpt('root_helper', default='sudo'),
        ]
        self.conf = cfg.CONF
        self.conf.register_opts(root_helper_opt)
        self.ip_dev_p = mock.patch.object(ip_lib, 'IPDevice')
        self.ip_dev = self.ip_dev_p.start()
        self.ip_p = mock.patch.object(ip_lib, 'IPWrapper')
        self.ip = self.ip_p.start()
        self.device_exists_p = mock.patch.object(ip_lib, 'device_exists')
        self.device_exists = self.device_exists_p.start()

    def tearDown(self):
        # sometimes a test may turn this off
        try:
            self.device_exists_p.stop()
        except RuntimeError:
            pass
        self.ip_dev_p.stop()
        self.ip_p.stop()
        # Note(rods): some tests override the default options so let's reset
        # the config object
        self.conf.reset()


class TestABCDriver(TestBase):
    def test_get_device_name(self):
        bc = BaseChild(self.conf)
        device_name = bc.get_device_name(FakePort())
        self.assertEqual('tapabcdef01-12', device_name)

    def test_l3_init(self):
        addresses = [dict(ip_version=4, scope='global',
                          dynamic=False, cidr='172.16.77.240/24')]
        self.ip_dev().addr.list = mock.Mock(return_value=addresses)

        bc = BaseChild(self.conf)
        ns = '12345678-1234-5678-90ab-ba0987654321'
        bc.init_l3('tap0', ['192.168.1.2/24'], namespace=ns)
        self.ip_dev.assert_has_calls(
            [mock.call('tap0', 'sudo', namespace=ns),
             mock.call().addr.list(scope='global', filters=['permanent']),
             mock.call().addr.add(4, '192.168.1.2/24', '192.168.1.255'),
             mock.call().addr.delete(4, '172.16.77.240/24')])


class TestOVSInterfaceDriver(TestBase):

    def test_plug_no_ns(self):
        self._test_plug()

    def test_plug_with_ns(self):
        self._test_plug(namespace='01234567-1234-1234-99')

    def test_plug_alt_bridge(self):
        self._test_plug(bridge='br-foo')

    def _test_plug(self, additional_expectation=[], bridge=None,
                   namespace=None):

        if not bridge:
            bridge = 'br-int'

        def device_exists(dev, root_helper=None, namespace=None):
            return dev == bridge

        vsctl_cmd = ['ovs-vsctl', '--', '--may-exist', 'add-port',
                     bridge, 'tap0', '--', 'set', 'Interface', 'tap0',
                     'type=internal', '--', 'set', 'Interface', 'tap0',
                     'external-ids:iface-id=port-1234', '--', 'set',
                     'Interface', 'tap0',
                     'external-ids:iface-status=active', '--', 'set',
                     'Interface', 'tap0',
                     'external-ids:attached-mac=aa:bb:cc:dd:ee:ff']

        with mock.patch.object(utils, 'execute') as execute:
            ovs = interface.OVSInterfaceDriver(self.conf)
            self.device_exists.side_effect = device_exists
            ovs.plug('01234567-1234-1234-99',
                     'port-1234',
                     'tap0',
                     'aa:bb:cc:dd:ee:ff',
                     bridge=bridge,
                     namespace=namespace)
            execute.assert_called_once_with(vsctl_cmd, 'sudo')

        expected = [mock.call('sudo'),
                    mock.call().device('tap0'),
                    mock.call().device().link.set_address('aa:bb:cc:dd:ee:ff')]
        expected.extend(additional_expectation)
        if namespace:
            expected.extend(
                [mock.call().ensure_namespace(namespace),
                 mock.call().ensure_namespace().add_device_to_namespace(
                     mock.ANY)])
        expected.extend([mock.call().device().link.set_up()])

        self.ip.assert_has_calls(expected)

    def test_plug_mtu(self):
        self.conf.set_override('network_device_mtu', 9000)
        self._test_plug([mock.call().device().link.set_mtu(9000)])

    def test_unplug(self, bridge=None):
        if not bridge:
            bridge = 'br-int'
        with mock.patch('akanda.rug.common.linux.ovs_lib.OVSBridge') as ovs_br:
            ovs = interface.OVSInterfaceDriver(self.conf)
            ovs.unplug('tap0')
            ovs_br.assert_has_calls([mock.call(bridge, 'sudo'),
                                     mock.call().delete_port('tap0')])


class TestBridgeInterfaceDriver(TestBase):
    def test_get_device_name(self):
        br = interface.BridgeInterfaceDriver(self.conf)
        device_name = br.get_device_name(FakePort())
        self.assertEqual('ns-abcdef01-12', device_name)

    def test_plug_no_ns(self):
        self._test_plug()

    def test_plug_with_ns(self):
        self._test_plug(namespace='01234567-1234-1234-99')

    def _test_plug(self, namespace=None):
        def device_exists(device, root_helper=None, namespace=None):
            return device.startswith('brq')

        root_veth = mock.Mock()
        ns_veth = mock.Mock()

        self.ip().add_veth = mock.Mock(return_value=(root_veth, ns_veth))

        self.device_exists.side_effect = device_exists
        br = interface.BridgeInterfaceDriver(self.conf)
        br.plug('01234567-1234-1234-99',
                'port-1234',
                'ns-0',
                'aa:bb:cc:dd:ee:ff',
                namespace=namespace)

        ip_calls = [mock.call('sudo'), mock.call().add_veth('tap0', 'ns-0')]
        if namespace:
            ip_calls.extend([
                mock.call().ensure_namespace('01234567-1234-1234-99'),
                mock.call().ensure_namespace().add_device_to_namespace(
                    ns_veth)])

        self.ip.assert_has_calls(ip_calls)

        root_veth.assert_has_calls([mock.call.link.set_up()])
        ns_veth.assert_has_calls([mock.call.link.set_up()])

    def test_plug_dev_exists(self):
        self.device_exists.return_value = True
        with mock.patch(
                'akanda.rug.common.linux.interface.LOG.warning') as log:
            br = interface.BridgeInterfaceDriver(self.conf)
            br.plug('01234567-1234-1234-99',
                    'port-1234',
                    'tap0',
                    'aa:bb:cc:dd:ee:ff')
            self.ip_dev.assert_has_calls([])
            self.assertEquals(log.call_count, 1)

    def test_unplug_no_device(self):
        self.device_exists.return_value = False
        self.ip_dev().link.delete.side_effect = RuntimeError
        with mock.patch('akanda.rug.common.linux.interface.LOG') as log:
            br = interface.BridgeInterfaceDriver(self.conf)
            br.unplug('tap0')
            [mock.call(), mock.call('tap0', 'sudo'), mock.call().link.delete()]
            self.assertEqual(log.exception.call_count, 1)

    def test_unplug(self):
        self.device_exists.return_value = True
        with mock.patch('akanda.rug.common.linux.interface.LOG.debug') as log:
            br = interface.BridgeInterfaceDriver(self.conf)
            br.unplug('tap0')
            self.assertEqual(log.call_count, 1)

        self.ip_dev.assert_has_calls([mock.call('tap0', 'sudo', None),
                                      mock.call().link.delete()])
