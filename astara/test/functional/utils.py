# Copyright (c) 2016 Akanda, Inc. All Rights Reserved.
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

import netaddr
import re


PHYSICAL_INTERFACES = ['lo', 'eth', 'em', 're', 'en', 'vio', 'vtnet']


def parse_interfaces(data, filters=PHYSICAL_INTERFACES):
    """
    Parse the output of `ip addr show`.

    :param data: the output of `ip addr show`
    :type data: str
    :param filter: a list of valid interface names to match on
    :type data: list of str
    :rtype: list of astara_router.models.Interface
    """
    retval = {}
    for iface_data in re.split('(^|\n)(?=[0-9]+: \w+\d{0,3}:)', data):
        if not iface_data.strip():
            continue
        number, interface = iface_data.split(': ', 1)

        # FIXME (mark): the logic works, but should be more readable
        for f in filters or ['']:
            if f == '':
                break
            elif interface.startswith(f) and interface[len(f)].isdigit():
                break
        else:
            continue

        retval.update(_parse_interface(iface_data))
    return retval


def _parse_interface(data):
    """
    Parse details for an interface, given its data from `ip addr show <ifname>`

    :rtype: astara_router.models.Interface
    """
    retval = dict(addresses=[])
    ifname = None
    for line in data.split('\n'):
        if line.startswith(' '):
            line = line.strip()
            if line.startswith('inet'):
                retval['addresses'].append(_parse_inet(line))
            elif 'link/ether' in line:
                retval['lladdr'] = _parse_lladdr(line)
        else:
            ifname, data = _parse_head(line)
            retval.update(data)

    return {ifname: retval}


def _parse_head(line):
    """
    Parse the line of `ip addr show` that contains the interface name, MTU, and
    flags.
    """
    retval = {}
    m = re.match(
        '[0-9]+: (?P<if>\w+\d{1,3}): <(?P<flags>[^>]+)> mtu (?P<mtu>[0-9]+)',
        line
    )
    if m:
        ifname = m.group('if')
        retval['mtu'] = int(m.group('mtu'))
        retval['flags'] = m.group('flags').split(',')
    return ifname, retval


def _parse_inet(line):
    """
    Parse a line of `ip addr show` that contains an address.
    """
    tokens = line.split()
    return netaddr.IPNetwork(tokens[1])


def _parse_lladdr(line):
    """
    Parse the line of `ip addr show` that contains the hardware address.
    """
    tokens = line.split()
    return tokens[1]
