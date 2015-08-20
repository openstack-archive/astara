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

DRIVER_OPTS = [cfg.IntOpt('available_drivers',
                          default={},
                          help='a dictionary of the enabled drivers'), ]

cfg.CONF.register_opts(DRIVER_OPTS)


class MissingDriverException(Exception):
    """Triggered when driver is not available in AVAILABLE_DRIVERS"""
    pass


def get(requested_driver):
    """Returns driver class based on the requested_driver param
    will raise MissingDriverException if not listed in the config option
    cfg.CONF.available_drivers.

    :param requested_driver: name of desired driver
    :return: returns driver object
    """
    if requested_driver in cfg.CONF.available_drivers:
        return cfg.CONF.available_drivers[requested_driver]

    raise MissingDriverException()
