# Copyright 2016 Mark McClain
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

from astara_neutron.plugins import ml2_neutron_plugin as as_plugin

from neutron.plugins.ml2 import plugin as ml2_plugin
from neutron.services.l3_router.service_providers import base


class SingleNodeDriver(base.L3ServiceProvider):
    """Provider for single L3 agent routers."""
    use_integrated_agent_scheduler = False


class HaNodeDriver(base.L3ServiceProvider):
    """Provider for HA L3 agent routers."""
    use_integrated_agent_schedule = False


class Ml2Plugin(as_plugin.Ml2Plugin):
    _supported_extension_aliases = (
        as_plugin.Ml2Plugin._supported_extension_aliases +
        ['ip_allocation']
    )

    disabled_extensions = [
        "dhrouterstatus",
        "byonf"
    ]

    for ext in disabled_extensions:
        try:
            _supported_extension_aliases.remove(ext)
        except ValueError:
            pass

    def _make_port_dict(self, port, fields=None, process_extensions=True):
        res = ml2_plugin.Ml2Plugin._make_port_dict(
            self,
            port,
            fields,
            process_extensions
        )
        if not res.get('fixed_ips') and res.get('mac_address'):
            res['ip_allocation'] = 'deferred'
        return res
