# Copyright 2015 Akanda, Inc.
#
# Author: Akanda, Inc.
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

import abc
import six

from oslo_config import cfg
from oslo_db import api as db_api


_BACKEND_MAPPING = {
    'sqlalchemy': 'akanda.rug.db.sqlalchemy.api'
}

IMPL = db_api.DBAPI.from_config(
    cfg.CONF, backend_mapping=_BACKEND_MAPPING, lazy=True)


def get_instance():
    return IMPL


@six.add_metaclass(abc.ABCMeta)
class Connection(object):
    @abc.abstractmethod
    def __init__(self):
        pass

    @abc.abstractmethod
    def enable_resource_debug(self, resource_uuid, reason=None):
        """Enter a resource into debug mode

        :param resource_uuid: str uuid of the resource to be placed into debug
                            mode
        :param reason: str (optional) reason for entering resource into debug
                       mode
        """

    @abc.abstractmethod
    def disable_resource_debug(self, resource_uuid):
        """Remove a resource into debug mode

        :param resource_uuid: str uuid of the resource to be removed from debug
                            mode
        """

    @abc.abstractmethod
    def resource_in_debug(self, resource_uuid):
        """Determines if a resource is in debug mode

        :param resource_uuid: str the uuid of the resource to query
        :returns: tuple (False, None) if resource is not in debug mode or
                  (True, "reason") if it is.
        """

    @abc.abstractmethod
    def resources_in_debug(self):
        """Queries all resources in debug mode

        :returns: a set of (resource_uuid, reason) tuples
        """

    @abc.abstractmethod
    def enable_tenant_debug(self, tenant_uuid, reason=None):
        """Enter a tenant into debug mode

        :param tenant_uuid: str uuid of the tenant to be placed into debug
                            mode
        :param reason: str (optional) reason for entering tenant into debug
                       mode
        """

    @abc.abstractmethod
    def disable_tenant_debug(self, tenant_uuid):
        """Remove a tenant into debug mode

        :param tenant_uuid: str uuid of the tenant to be removed from debug
                            mode
        """

    @abc.abstractmethod
    def tenant_in_debug(self, tenant_uuid):
        """Determines if a tenant is in debug mode

        :param tenant_uuid: str the uuid of the tenant to query
        :returns: tuple (False, None) if tenant is not in debug mode or
                  (True, "reason") if it is.
        """

    @abc.abstractmethod
    def tenants_in_debug(self):
        """Queries all tenants in debug mode

        :returns: a set of (tenant_uuid, reason) tuples
        """

    @abc.abstractmethod
    def enable_global_debug(self, reason=None):
        """Enter the entire system into debug mode
        :param reason: str (optional) reason for entering cluster into global
                       debug mode.
        """

    @abc.abstractmethod
    def disable_global_debug(self):
        """Remove the entire system from global debug mode"""

    @abc.abstractmethod
    def global_debug(self):
        """Determine whether cluster is in global debug mode

        :returns: bool True if cluster is in debug mode
        :returns: tuple (False, None) if cluster is not in global debug mode or
                  (True, "reason") if it is.
        """
