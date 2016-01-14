# Copyright (c) 2016 Akanda, Inc. All Rights Reserved.
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

import collections
import threading


class ResourceContainer(object):

    def __init__(self):
        self.resources = {}
        self.deleted = collections.deque(maxlen=50)
        self.lock = threading.Lock()

    def __delitem__(self, item):
        with self.lock:
            del self.resources[item]
            self.deleted.append(item)

    def items(self):
        """Get all state machines.
        :returns: all state machines in this RouterContainer
        """
        with self.lock:
            return list(self.resources.items())

    def values(self):
        with self.lock:
            return list(self.resources.values())

    def has_been_deleted(self, resource_id):
        """Check if a resource has been deleted.

        :param resource_id: The resource's id to check against the deleted list
        :returns: Returns True if the resource_id has been deleted.
        """
        with self.lock:
            return resource_id in self.deleted

    def __getitem__(self, item):
        with self.lock:
            return self.resources[item]

    def __setitem__(self, key, value):
        with self.lock:
            self.resources[key] = value

    def __contains__(self, item):
        with self.lock:
            return item in self.resources

    def __bool__(self):
        if self.values():
            return True
        else:
            return False

    def __nonzero__(self):
        return self.__bool__()
