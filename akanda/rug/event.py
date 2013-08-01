"""Common event format for events passed within the RUG
"""

import collections

Event = collections.namedtuple(
    'Event',
    ['tenant_id', 'router_id', 'crud', 'body'],
)

CREATE = 'create'
READ = 'read'
UPDATE = 'update'
DELETE = 'delete'
POLL = 'poll'
