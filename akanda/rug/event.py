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


"""Common event format for events passed within the RUG
"""


class Event(object):
    def __init__(self, resource, crud, body):
        self.resource = resource
        self.crud = crud
        self.body = body

    def __eq__(self, other):
        if not type(self) == type(other):
            return False
        for k, v in vars(self).iteritems():
            if k not in vars(other):
                return False
            if vars(other)[k] != v:
                return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return '<%s (resource=%s, crud=%s, body=%s)>' % (
            self.__class__.__name__,
            self.resource,
            self.crud,
            self.body)


CREATE = 'create'
READ = 'read'
UPDATE = 'update'
DELETE = 'delete'
POLL = 'poll'
COMMAND = 'command'  # an external command to be processed
REBUILD = 'rebuild'
