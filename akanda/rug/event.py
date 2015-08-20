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

# CRUD operations tracked in Event.crud
CREATE = 'create'
READ = 'read'
UPDATE = 'update'
DELETE = 'delete'
POLL = 'poll'
COMMAND = 'command'  # an external command to be processed
REBUILD = 'rebuild'


class Event(object):
    """Rug Event object

    Events are constructed from incoming messages accepted by the Rug.
    They are responsible for holding the message payload (body), the
    correpsonding CRUD operation and the logical resource that the
    event affects.
    """
    def __init__(self, resource, crud, body):
        """
        :param resource: Resource instance holding context about the logical
                         resource that is affected by the Event.
        :param crud: CRUD operation that is to be completed by the
                     correpsonding state machine when it is delivered.
        :param body: The original message payload dict.
        """
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


class Resource(object):
    """Rug Resource object

    A Resource object represents one instance of a logical resource
    that is to be managed by the rug (ie, a router).
    """
    def __init__(self, driver, id, tenant_id):
        """
        :param driver: str name of the driver that corresponds to the resource
                       type.
        :param id: ID of the resource (ie, the Neutron router's UUID).
        :param tenant_id: The UUID of the tenant that owns this resource.
        """
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
