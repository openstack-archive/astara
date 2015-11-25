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


"""Base class for command that sends a message to the rug
"""
import abc
import logging

from cliff import command

from astara import notifications


class MessageSending(command.Command):

    __metaclass__ = abc.ABCMeta

    log = logging.getLogger(__name__)
    interactive = False

    @abc.abstractmethod
    def make_message(self, parsed_args):
        """Return a dictionary containing the message contents
        """
        return {}

    def take_action(self, parsed_args):
        self.log.info(
            'using amqp at %r exchange %r',
            self.app.rug_ini.amqp_url,
            self.app.rug_ini.outgoing_notifications_exchange,
        )
        self.send_message(self.make_message(parsed_args))

    def send_message(self, payload):
        sender = notifications.Sender()
        self.log.debug('sending %r', payload)
        sender.send(event_type='astara.command', message=payload)
