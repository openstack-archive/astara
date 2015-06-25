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
from akanda.rug.drivers.router import Router


class DriverFactory(object):

    @staticmethod
    def get_driver(name):
        """returns driver class based on the name param

        :param name: name of desired driver
        :return: returns driver object
        """
        if name == 'router':
            return Router

        raise Exception("No such driver exists")
