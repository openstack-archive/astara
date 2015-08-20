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
from oslo_log import log as logging


class BaseDriver(object):

    RESOURCE_NAME = 'base'
    flavor = None
    name = None

    def __init__(self, id, log=None):
        """This is the base for drivers.

        :param id: logical resource id
        :param log: override default log
        """
        self.id = id
        self.external_port = None

        self.name = 'ak-%s-%s' % (self.RESOURCE_NAME, self.id)

        if log:
            self.log = log
        else:
            self.log = logging.getLogger(self.RESOURCE_NAME + '.' + id)

    def pre_boot(self, worker_context):
        """pre boot hook

        :param worker_context:
        :returns: None
        """
        pass

    def post_boot(self, worker_context):
        """post boot hook

        :param worker_context:
        :returns: None
        """
        pass

    def update_state(self, worker_context, silent=False):
        """returns state of logical resource.

        :param worker_context:
        :param silent:
        :returns: None
        """
        pass

    def get_config(self, worker_context):
        """gets config of logical resource attached to worker_context.

        :param worker_context:
        :returns: None
        """
        pass
