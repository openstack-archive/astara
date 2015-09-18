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

from oslo_config import cfg
from oslo_log import log as logging

from akanda.rug import event
from akanda.rug import drivers

LOG = logging.getLogger(__name__)


def _pre_populate_workers(scheduler):
    """Loops through enabled drivers triggering each drivers pre_populate_hook
    which is a static method for each driver.

    """
    LOG.debug('Pre-populating for configured drivers: %s',
              cfg.CONF.enabled_drivers)
    for driver_obj in drivers.enabled_drivers():
        resources = driver_obj.pre_populate_hook()

        if not resources:
            # just skip to the next one the drivers pre_populate_hook already
            # handled the exception or error and outputs to logs
            LOG.debug('No %s resources found to pre-populate',
                      driver_obj.RESOURCE_NAME)
            continue

        LOG.debug('Start pre-populating %d workers for the %s driver',
                  len(resources),
                  driver_obj.RESOURCE_NAME)

        for resource in resources:
            message = event.Event(
                resource=resource,
                crud=event.POLL,
                body={}
            )
            scheduler.handle_message(resource.tenant_id, message)


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
