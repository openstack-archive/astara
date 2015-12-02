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

# Copyright 2012 OpenStack Foundation
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

import abc

import netaddr

from oslo_config import cfg
from oslo_log import log as logging

from akanda.rug.common.i18n import _, _LE, _LW
from akanda.rug.common.linux import ip_lib
from akanda.rug.common.linux import ovs_lib
from akanda.rug.common.linux import utils


LOG = logging.getLogger(__name__)
CONF = cfg.CONF


OPTS = [
    cfg.StrOpt('ovs_integration_bridge',
               default='br-int',
               help=_('Name of Open vSwitch bridge to use')),
    cfg.BoolOpt('ovs_use_veth',
                default=False,
                help=_('Uses veth for an interface or not')),
    cfg.StrOpt('network_device_mtu',
               help=_('MTU setting for device.')),
]
CONF.register_opts(OPTS)


# NOTE(adam_g): These need a better home
AGENT_OPTIONS = [
    cfg.StrOpt('root_helper', default='sudo'),
]
CONF.register_group(cfg.OptGroup(name='AGENT'))
CONF.register_opts(AGENT_OPTIONS, 'AGENT')


class LinuxInterfaceDriver(object):
    __metaclass__ = abc.ABCMeta

    # from linux IF_NAMESIZE
    DEV_NAME_LEN = 14
    DEV_NAME_PREFIX = 'tap'

    def __init__(self, conf):
        self.conf = conf
        self.root_helper = conf.AGENT.root_helper

    def init_l3(self, device_name, ip_cidrs, namespace=None):
        """Set the L3 settings for the interface using data from the port.
           ip_cidrs: list of 'X.X.X.X/YY' strings
        """
        device = ip_lib.IPDevice(device_name,
                                 self.root_helper,
                                 namespace=namespace)

        previous = {}
        for address in device.addr.list(scope='global', filters=['permanent']):
            previous[address['cidr']] = address['ip_version']

        # add new addresses
        for ip_cidr in ip_cidrs:

            net = netaddr.IPNetwork(ip_cidr)
            if ip_cidr in previous:
                del previous[ip_cidr]
                continue

            device.addr.add(net.version, ip_cidr, str(net.broadcast))

        # clean up any old addresses
        for ip_cidr, ip_version in previous.items():
            device.addr.delete(ip_version, ip_cidr)

    def check_bridge_exists(self, bridge):
        if not ip_lib.device_exists(bridge):
            raise Exception(_('Bridge %s does not exist') % bridge)

    def get_device_name(self, port):
        return (self.DEV_NAME_PREFIX + port.id)[:self.DEV_NAME_LEN]

    @abc.abstractmethod
    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        """Plug in the interface."""

    @abc.abstractmethod
    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        """Unplug the interface."""


class NullDriver(LinuxInterfaceDriver):
    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        pass

    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        pass


class OVSInterfaceDriver(LinuxInterfaceDriver):
    """Driver for creating an internal interface on an OVS bridge."""

    DEV_NAME_PREFIX = 'tap'

    def __init__(self, conf):
        super(OVSInterfaceDriver, self).__init__(conf)
        if self.conf.ovs_use_veth:
            self.DEV_NAME_PREFIX = 'ns-'

    def _get_tap_name(self, dev_name, prefix=None):
        if self.conf.ovs_use_veth:
            dev_name = dev_name.replace(prefix or self.DEV_NAME_PREFIX, 'tap')
        return dev_name

    def _ovs_add_port(self, bridge, device_name, port_id, mac_address,
                      internal=True):
        cmd = ['ovs-vsctl', '--', '--may-exist',
               'add-port', bridge, device_name]
        if internal:
            cmd += ['--', 'set', 'Interface', device_name, 'type=internal']
        cmd += ['--', 'set', 'Interface', device_name,
                'external-ids:iface-id=%s' % port_id,
                '--', 'set', 'Interface', device_name,
                'external-ids:iface-status=active',
                '--', 'set', 'Interface', device_name,
                'external-ids:attached-mac=%s' % mac_address]
        utils.execute(cmd, self.root_helper)

    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        """Plug in the interface."""
        if not bridge:
            bridge = self.conf.ovs_integration_bridge

        self.check_bridge_exists(bridge)

        if not ip_lib.device_exists(device_name,
                                    self.root_helper,
                                    namespace=namespace):

            ip = ip_lib.IPWrapper(self.root_helper)
            tap_name = self._get_tap_name(device_name, prefix)

            if self.conf.ovs_use_veth:
                root_dev, ns_dev = ip.add_veth(tap_name, device_name)

            internal = not self.conf.ovs_use_veth
            self._ovs_add_port(bridge, tap_name, port_id, mac_address,
                               internal=internal)

            ns_dev = ip.device(device_name)
            ns_dev.link.set_address(mac_address)

            if self.conf.network_device_mtu:
                ns_dev.link.set_mtu(self.conf.network_device_mtu)
                if self.conf.ovs_use_veth:
                    root_dev.link.set_mtu(self.conf.network_device_mtu)

            if namespace:
                namespace_obj = ip.ensure_namespace(namespace)
                namespace_obj.add_device_to_namespace(ns_dev)

            ns_dev.link.set_up()
            if self.conf.ovs_use_veth:
                root_dev.link.set_up()
        else:
            LOG.warning(_LW("Device %s already exists"), device_name)

    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        """Unplug the interface."""
        if not bridge:
            bridge = self.conf.ovs_integration_bridge

        tap_name = self._get_tap_name(device_name, prefix)
        self.check_bridge_exists(bridge)
        ovs = ovs_lib.OVSBridge(bridge, self.root_helper)

        try:
            ovs.delete_port(tap_name)
            if self.conf.ovs_use_veth:
                device = ip_lib.IPDevice(device_name,
                                         self.root_helper,
                                         namespace)
                device.link.delete()
                LOG.debug(_("Unplugged interface '%s'"), device_name)
        except RuntimeError:
            LOG.exception(_LE("Failed unplugging interface '%s'"), device_name)


class BridgeInterfaceDriver(LinuxInterfaceDriver):
    """Driver for creating bridge interfaces."""

    DEV_NAME_PREFIX = 'ns-'

    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        """Plugin the interface."""
        if not ip_lib.device_exists(device_name,
                                    self.root_helper,
                                    namespace=namespace):
            ip = ip_lib.IPWrapper(self.root_helper)

            # Enable agent to define the prefix
            if prefix:
                tap_name = device_name.replace(prefix, 'tap')
            else:
                tap_name = device_name.replace(self.DEV_NAME_PREFIX, 'tap')
            root_veth, ns_veth = ip.add_veth(tap_name, device_name)
            ns_veth.link.set_address(mac_address)

            if self.conf.network_device_mtu:
                root_veth.link.set_mtu(self.conf.network_device_mtu)
                ns_veth.link.set_mtu(self.conf.network_device_mtu)

            if namespace:
                namespace_obj = ip.ensure_namespace(namespace)
                namespace_obj.add_device_to_namespace(ns_veth)

            root_veth.link.set_up()
            ns_veth.link.set_up()

        else:
            LOG.warning(_LW("Device %s already exists"), device_name)

    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        """Unplug the interface."""
        device = ip_lib.IPDevice(device_name, self.root_helper, namespace)
        try:
            device.link.delete()
            LOG.debug("Unplugged interface '%s'", device_name)
        except RuntimeError:
            LOG.exception(_LE(
                "Failed unplugging interface '%s'"), device_name)
