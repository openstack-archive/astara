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

from oslo_config import cfg
from astara.test.functional import base

CONF = cfg.CONF


class AstaraApplianceInstanceTest(base.AstaraFunctionalBase):
    """Basic tests to ensure a service instance and its associated router is
    alive and well.
    """
    def setUp(self):
        super(AstaraApplianceInstanceTest, self).setUp()
        # ensure the devstack spawned router instance becomes active before
        # starting to run any test cases. this in itself is a test that
        # devstack produced a functional router.
        self.assert_router_is_active()

    def test_appliance_is_alive(self):
        router_uuid = CONF.astara_test_router_uuid
        self.assertTrue(
            self.ak_client.is_alive(
                host=self.get_management_address(router_uuid),
                port=CONF.appliance_api_port,
                timeout=10,
            ),
        )
