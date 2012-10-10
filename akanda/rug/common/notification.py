import inspect
import logging

from akanda.rug.openstack.common import rpc

LOG = logging.getLogger(__name__)

_HANDLER_ATTR = '_notification_handle_event_type'


class NotificationMixin(object):
    def create_notification_listener(self, topic, exchange_name=None):
        self._notification_handlers = {}
        for method in inspect.getmembers(self, inspect.ismethod):
            for event_type in getattr(method[1], _HANDLER_ATTR, []):
                self._notification_handlers.setdefault(
                    event_type, []).append(method[1])

        self.notification_connection = rpc.create_connection(new=True)
        self.notification_connection.declare_topic_consumer(
            topic=topic,
            callback=self._notification_mixin_dispatcher,
            exchange_name=exchange_name)
        self.notification_connection.consume_in_thread()

    def _notification_mixin_dispatcher(self, msg):
        try:
            handlers = self._notification_handlers.get(msg['event_type'], [])
            if handlers:
                for h in handlers:
                    h(msg['_context_tenant_id'], msg['payload'])
            else:
                if hasattr(self, 'default_notification_handler'):
                    self.default_notification_handler(
                        msg['event_type'],
                        msg['_context_tenant_id'],
                        msg['payload'])

        except Exception, e:
            LOG.exception('Error processing notification.')


def handles(*event_types):
    def deco(f):
        if not hasattr(f, _HANDLER_ATTR):
            setattr(f, _HANDLER_ATTR, list(event_types))
        else:
            getattr(f, _HANDLER_ATTR).extend(event_types)
        return f
    return deco
