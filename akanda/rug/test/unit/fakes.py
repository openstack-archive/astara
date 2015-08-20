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

import mock

from akanda.rug.drivers import base


def fake_driver(resource_id=None):
    """A factory for generating fake driver instances suitable for testing"""
    fake_driver = mock.Mock(base.BaseDriver, autospec=True)
    fake_driver.RESOURCE_NAME = 'FakeDriver'
    fake_driver.id = resource_id or 'fake_resource_id'
    fake_driver.log = mock.Mock()
    fake_driver.flavor = 'fake_flavor'
    fake_driver.name = 'ak-FakeDriver-fake_resource_id'
    fake_driver.image_uuid = 'fake_image_uuid'
    fake_driver.make_ports.return_value = 'fake_ports_callback'
    return fake_driver
