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


"""Populate the workers with the existing routers
"""

import threading
import time

from oslo_config import cfg
from oslo_log import log as logging

from neutronclient.common import exceptions as q_exceptions

from akanda.rug import event
from akanda.rug.api import neutron

from akanda.rug.common.i18n import _LW

LOG = logging.getLogger(__name__)


def _pre_populate_workers(scheduler):
    """Fetch the existing routers from neutron.

    Wait for neutron to return the list of the existing routers.
    Pause up to max_sleep seconds between each attempt and ignore
    neutron client exceptions.


    """
    nap_time = 1
    max_sleep = 15

    neutron_client = neutron.Neutron(cfg.CONF)

    while True:
        try:
            neutron_routers = neutron_client.get_routers(detailed=False)
            break
        except (q_exceptions.Unauthorized, q_exceptions.Forbidden) as err:
            LOG.warning(_LW('PrePopulateWorkers thread failed: %s'), err)
            return
        except Exception as err:
            LOG.warning(
                _LW('Could not fetch routers from neutron: %s'), err)
            LOG.warning(_LW('sleeping %s seconds before retrying'), nap_time)
            time.sleep(nap_time)
            # FIXME(rods): should we get max_sleep from the config file?
            nap_time = min(nap_time * 2, max_sleep)

    LOG.debug('Start pre-populating the workers with %d fetched routers',
              len(neutron_routers))

    for router in neutron_routers:
        message = event.Event(
            tenant_id=router.tenant_id,
            router_id=router.id,
            crud=event.POLL,
            body={}
        )
        scheduler.handle_message(router.tenant_id, message)


def pre_populate_workers(scheduler):
    """Start the pre-populating task
    """

    t = threading.Thread(
        target=_pre_populate_workers,
        args=(scheduler,),
        name='PrePopulateWorkers'
    )

    t.setDaemon(True)
    t.start()
    return t
