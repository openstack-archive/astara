"""Listen for notifications.
"""


def listen(notification_queue):
    # TODO(dhellmann): Replace with a version of the service code from
    # oslo that knows how to subscribe to notifications.
    for i in range(5):
        notification_queue.put({'key': 'value'})
