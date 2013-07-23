"""Listen for notifications.
"""

import uuid


def listen(notification_queue):
    # TODO(dhellmann): Replace with a version of the service code from
    # oslo that knows how to subscribe to notifications.
    for i in range(5):
        router_id = uuid.UUID('7fe12bca-f3cb-11e2-9084-080027e60b1%d' % i)
        notification_queue.put(
            (str(router_id),
             {
                 'key': 'value',
                 'id': str(router_id),
             },
         ))
