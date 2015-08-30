# Copyright (c) 2015 AKANDA, INC. All Rights Reserved.
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


class Resource(object):
    def __init__(self, driver, _id, _tenant_id):
        """This is generic resource object

        :params driver: a string, should match one in drivers.AVAILABLE_DRIVERS
        :params id: the logical resources id, for a router it would be
        a neutron router id.
        """
        self.driver = driver
        self.id = _id
        self.tenant_id = _tenant_id
