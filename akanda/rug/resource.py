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
    def __init__(self, driver, id, tenant_id):
        self.driver = driver
        self.id = id
        self.tenant_id = tenant_id

    def __eq__(self, other):
        return type(self) == type(other) and vars(self) == vars(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return '<%s (driver=%s, id=%s, tenant_id=%s)>' % (
            self.__class__.__name__,
            self.driver,
            self.id,
            self.tenant_id)
