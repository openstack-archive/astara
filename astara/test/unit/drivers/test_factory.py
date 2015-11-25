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

from astara.test.unit import base

from astara import drivers


class DriverFactoryTest(base.RugTestBase):
    def test_get_driver(self):
        for k, v in drivers.AVAILABLE_DRIVERS.iteritems():
            self.assertEqual(drivers.get(k), v)

    def test_get_bad_driver(self):
        self.assertRaises(
            drivers.InvalidDriverException,
            drivers.get, 'foodriver'
        )

    def test_enabled_drivers(self):
        all_driver_cfg = drivers.AVAILABLE_DRIVERS.keys()
        all_driver_obj = drivers.AVAILABLE_DRIVERS.values()
        self.config(enabled_drivers=all_driver_cfg)
        enabled_drivers = [d for d in drivers.enabled_drivers()]
        self.assertEqual(set(all_driver_obj), set(enabled_drivers))

    def test_enabled_drivers_nonexistent_left_out(self):
        all_driver_cfg = drivers.AVAILABLE_DRIVERS.keys() + ['foodriver']
        all_driver_obj = drivers.AVAILABLE_DRIVERS.values()
        self.config(enabled_drivers=all_driver_cfg)
        enabled_drivers = [d for d in drivers.enabled_drivers()]
        self.assertEqual(set(all_driver_obj), set(enabled_drivers))
