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

# TODO: (david) make available drivers a config section
available_drivers = {}


class MissingDriverException(Exception):
    """triggered when driver is not available in available_drivers"""
    pass


def get(requested_driver):
    """returns driver class based on the name param

    :param name: name of desired driver
    :return: returns driver object
    """

    if requested_driver in available_drivers:
        return available_drivers[requested_driver]

    raise MissingDriverException()
