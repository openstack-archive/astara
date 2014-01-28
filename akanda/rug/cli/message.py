"""Base class for command that sends a message to the rug
"""
import abc
import logging

from cliff import command

from akanda.rug import notifications


class MessageSending(command.Command):

    __metaclass__ = abc.ABCMeta

    log = logging.getLogger(__name__)

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
        payload = self.make_message(parsed_args)
        msg = {
            'event_type': 'akanda.rug.command',
            'payload': payload,
        }
        with notifications.Sender(
                amqp_url=self.app.rug_ini.amqp_url,
                exchange_name=self.app.rug_ini.outgoing_notifications_exchange,
                topic='notifications.info',
        ) as sender:
            sender.send(msg)
