# Copyright (c) 2015 Akanda, Inc. All Rights Reserved.
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

import time

from oslo_config import cfg
from oslo_log import log as logging

from astara.test.functional import base


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class TestAstaraRouter(base.AstaraFunctionalBase):
    @classmethod
    def setUpClass(cls):
        super(TestAstaraRouter, cls).setUpClass()
        cls.tenant = cls.get_tenant()
        cls.neutronclient = cls.tenant.clients.neutronclient
        cls.network, cls.router = cls.tenant.setup_networking()

    def setUp(self):
        super(TestAstaraRouter, self).setUp()
        self.assert_router_is_active(self.router['id'])

        # refresh router ref now that its active
        router = self.neutronclient.show_router(self.router['id'])
        self.router = router['router']

    def test_router_recovery(self):
        """
        Test that creation of network/subnet/router results in a
        correctly plugged appliance, and that manually destroying the
        Nova instance results in a new appliance being booted.
        """
        # for each subnet that was created during setup, ensure we have a
        # router interface added
        ports = self.neutronclient.list_ports()['ports']
        subnets = self.neutronclient.list_subnets(
            network_id=self.network['id'])
        subnets = subnets['subnets']
        self.assertEqual(len(ports), len(subnets))
        for port in ports:
            self.assertEqual(port['device_owner'], 'network:router_interface')
            self.assertEqual(port['device_id'], self.router['id'])
            self.assertEqual(
                sorted([subnet['id'] for subnet in subnets]),
                sorted([fip['subnet_id'] for fip in port['fixed_ips']])
            )

        self.ping_router_mgt_address(self.router['id'])

        # Ensure that if we destroy the nova instance, the RUG will rebuild
        # the router with a new instance.
        # This could live in a separate test case but it'd require the
        # above as setup, so just piggyback on it.

        old_server = self.get_router_appliance_server(self.router['id'])
        LOG.debug('Original server: %s', old_server)

        # NOTE(adam_g): In the gate, sometimes the appliance hangs on the
        # first config update and health checks get queued up behind the
        # hanging config update.  If thats the case, we need to wait a while
        # before deletion for the first to timeout.
        time.sleep(30)
        LOG.debug('Deleting original nova server: %s', old_server.id)
        self.admin_clients.novaclient.servers.delete(old_server.id)

        LOG.debug('Waiting %s seconds for astara health check to tick',
                  CONF.health_check_period)
        time.sleep(CONF.health_check_period)

        # look for the new server, retry giving rug time to do its thing.
        new_server = self.get_router_appliance_server(
            self.router['id'], retries=60, wait_for_active=True)
        LOG.debug('Rebuilt new server found: %s', new_server)
        self.assertNotEqual(old_server.id, new_server.id)

        # routers report as ACTIVE initially (LP: #1491673)
        time.sleep(2)

        self.assert_router_is_active(self.router['id'])
        self.ping_router_mgt_address(self.router['id'])
