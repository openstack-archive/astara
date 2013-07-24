"""Listen for notifications.
"""

import logging
import uuid

LOG = logging.getLogger(__name__)


def listen(notification_queue):
    LOG.debug('starting')
    # TODO(dhellmann): Replace with a version of the service code from
    # oslo that knows how to subscribe to notifications.
    for i in range(5):
        router_id = uuid.UUID('7fe12bca-f3cb-11e2-9084-080027e60b1%d' % i)
        fake_message = {
            'key': 'value',
            'id': str(router_id),
        }
        notification_queue.put((str(router_id), fake_message))
