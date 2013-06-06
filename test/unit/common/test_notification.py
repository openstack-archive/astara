import mock
import unittest2 as unittest

from akanda.rug.common import notification


class NotificationTest(notification.NotificationMixin):
    @notification.handles('foo')
    def handle_foo(self, tenant_id, payload):
        pass

    @notification.handles('bar')
    @notification.handles('baz')
    def handle_multi(self, tenant_id, payload):
        pass

    def default_notification_handler(self):
        pass


class TestNotificationMixin(unittest.TestCase):
    def test_init(self):
        n = NotificationTest()

    def test_create_listener(self):
        with mock.patch.object(notification, 'rpc') as rpc:
            n = NotificationTest()
            n.create_notification_listener('the_topic', 'the_exch')

            expected = [
                mock.call.create_connection(new=True),
                mock.call.create_connection().join_consumer_pool(
                    n._notification_mixin_dispatcher,
                    'akanda.notifications',
                    'the_topic',
                    exchange_name='the_exch'),
                mock.call.create_connection().consume_in_thread()]

            rpc.assert_has_calls(expected)
            self.assertEqual(n._notification_handlers,
                             {'foo': [n.handle_foo],
                              'bar': [n.handle_multi],
                              'baz': [n.handle_multi]})

    def test_dispatcher_known_event_type(self):
        test_message = {
            'event_type': 'foo',
            '_context_tenant_id': 'tenant_id',
            'payload': 'the_payload'
        }

        mock_handler = mock.Mock()

        n = NotificationTest()
        n._notification_handlers = {'foo': [mock_handler]}

        n._notification_mixin_dispatcher(test_message)
        mock_handler.assert_called_once_with('tenant_id', 'the_payload')

    def test_dispatcher_unknown_event_type(self):
        test_message = {
            'event_type': 'mystery',
            '_context_tenant_id': 'tenant_id',
            'payload': 'the_payload'
        }

        n = NotificationTest()
        n._notification_handlers = {}

        with mock.patch.object(n, 'default_notification_handler') as dh:
            n._notification_mixin_dispatcher(test_message)
            dh.assert_called_once_with('mystery', 'tenant_id', 'the_payload')

    def test_exception_during_dispatcher(self):
        test_message = {
            'event_type': 'foo',
            '_context_tenant_id': 'tenant_id',
            'payload': 'the_payload'
        }

        mock_handler = mock.Mock()
        mock_handler.side_effect = Exception

        n = NotificationTest()
        n._notification_handlers = {'foo': [mock_handler]}

        with mock.patch.object(notification, 'LOG') as log:
            n._notification_mixin_dispatcher(test_message)
            mock_handler.assert_called_once_with('tenant_id', 'the_payload')
            log.assert_has_calls([mock.call.exception(mock.ANY)])

    def test_dispatcher_with_no_context_tenant_id(self):
        test_message = {
            'event_type': 'foo',
            'payload': 'the_payload'
        }

        mock_method = mock.Mock()

        n = NotificationTest()
        n._notification_handlers = {}
        n.default_notification_handler = mock_method

        n._notification_mixin_dispatcher(test_message)
        mock_method.assert_called_once_with('foo', None, 'the_payload')
