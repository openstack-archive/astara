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
from oslo_config import cfg
from oslo_log import log as logging


class BaseDriver(object):

    RESOURCE_NAME = 'base'

    def __init__(self, id, worker_context, image_uuid=None, log=None):
        """This is the abstract for rug drivers.

        :param id: logical resource id
        :param worker_context: worker context object
        :param image_uuid: override the default image_uuid
        :param log: override default log
        """
        self._id = id
        self.worker_context = worker_context
        self.external_port = None

        if image_uuid:
            self.image_uuid = image_uuid
        else:
            self.image_uuid = self.default_image_uuid

        if log:
            self.log = log
        else:
            self.log = logging.getLogger(self.RESOURCE_NAME + '.' + id)

    @property
    def id(self):
        """get property id

        :return: self._id
        """
        return self._id

    @id.setter
    def id(self, value):
        """setter for id

        :param value:
        :return: None
        """
        self._id = value

    @property
    def default_image_uuid(self):
        """Returns default image uuid from base config

        :return: uuid string value from config file
        """
        return cfg.CONF.default_image_uuid

    def pre_boot(self):
        """pre-boot hook

        :return: pass
        """
        pass

    def pre_plug(self):
        """pre-plug hook

        :param worker_context:
        :param logical_obj:
        :return: pass
        """
        pass

    @staticmethod
    def update_status(worker_context, logical_obj, status):
        """Updates status of logical resource

        :param worker_context: worker_context object
        :param logical_obj: logical object
        :param status:
        :return: pass
        """
        pass

    @staticmethod
    def get_logical_config(worker_context, logical_id):
        """static method gets logical config of the logical resource passed in

        :param worker_context: worker_context object
        :param logical_id: id of logical resource
        :return: pass
        """
        pass

    @staticmethod
    def build_config(worker_context, logical_obj, instance_info, meta):
        """Builds / rebuilds config

        :param worker_context:
        :param logical_obj:
        :param instance_info:
        :param meta:
        :return: pass
        """
        pass
