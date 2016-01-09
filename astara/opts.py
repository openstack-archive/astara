#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import copy
import itertools
import operator
from keystoneauth1 import loading as ks_loading
from oslo_config import cfg
import astara.api.nova
import astara.drivers
import astara.main
import astara.common.linux.interface
import astara.notifications
import astara.coordination
import astara.pez.manager
import astara.drivers.router
import astara.api.rug
import astara.debug

def list_opts():
    return [
        ('DEFAULT',
         itertools.chain(
             astara.api.api_opts,
             astara.api.rug.RUG_API_OPTS,
             astara.api.nova.OPTIONS,
             astara.api.neutron.neutron_opts,
             astara.api.astara_client.AK_CLIENT_OPTS,
             astara.drivers.DRIVER_OPTS,
             astara.main.MAIN_OPTS,
             astara.common.linux.interface.OPTS,
             astara.common.hash_ring.hash_opts,
             astara.api.config.router.OPTIONS,
             astara.notifications.NOTIFICATIONS_OPTS,
             astara.debug.DEBUG_OPTS,
             astara.scheduler.SCHEDULER_OPTS,
             astara.worker.WORKER_OPTS,
             astara.metadata.METADATA_OPTS,
             astara.health.HEALTH_INSPECTOR_OPTS,
             astara.instance_manager.INSTANCE_MANAGER_OPTS
             )
        )
    ]

def list_agent_opts():
    return [
        ('AGENT', astara.common.linux.interface.AGENT_OPTIONS)
    ]

def list_coordination_opts():
    return [
        ('coordination', astara.coordination.COORD_OPTS)
    ]

def list_ceilometer_opts():
    return [
        ('ceilometer', astara.main.CEILOMETER_OPTS)
    ]

def list_router_opts():
    return [
        ('router', astara.drivers.router.ROUTER_OPTS)
    ]

def list_loadbalancer_opts():
    return [
        ('loadbalancer', astara.drivers.loadbalancer.ROUTER_OPTS)
    ]

def list_pez_opts():
    return [
        ('pez', astara.pez.manager.PEZ_OPTIONS)
    ]
