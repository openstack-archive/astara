import time

from akanda.rug import event as ak_event

from oslo_config import cfg
from oslo_log import log

import tooz
from tooz import coordination

import sys

LOG = log.getLogger(__name__)
CONF = cfg.CONF
#CONF.import_opt('host', 'akanda.rug.main')

COORD_OPTS = [
    cfg.StrOpt('url',
               default='memcached://localhost:11211',
               help='URL of suppoted coordination service'),
    cfg.StrOpt('host_id', default='localhost',
               help='Host ID to use for cluster registration, defaults to '
                    ' hostname.'),
    cfg.StrOpt('group_id', default='akanda.rug',
               help='ID of coordination group to join.'),
    cfg.IntOpt('heartbeat_interval', default=1),
]
CONF.register_group(cfg.OptGroup(name='coordination'))
CONF.register_opts(COORD_OPTS, group='coordination')


class InvalidEventType(Exception):
    pass



import os

class RugCoordinator(object):
    def __init__(self, notifications_queue):
        self._queue = notifications_queue
        self.host_id = os.getenv('HOST_ID') or CONF.coordination.host_id
        self.url = CONF.coordination.url
        self.group = CONF.coordination.group_id
        self.heartbeat_interval = CONF.coordination.heartbeat_interval
        self._coordinator = None
        self._group = None
        self.start()

    def start(self):
        LOG.info(
            'Starting RUG coordinator process for host %s on %s' %
            (self.host_id, self.url))
        self._coordinator = coordination.get_coordinator(
            self.url, self.host_id)
        self._coordinator.start()

        try:
            self._group = self._coordinator.create_group(self.group).get()
        except coordination.GroupAlreadyExist:
            pass
        try:
            self._coordinator.join_group(self.group).get()
            self._coordinator.heartbeat()
        except coordination.MemberAlreadyExist:
            pass

        self._coordinator.watch_join_group(self.group, self.cluster_changed)
        self._coordinator.watch_leave_group(self.group, self.cluster_changed)
        self._coordinator.heartbeat()
        LOG.debug("Sending initial event changed for members; %sx" %
                  self.members)
        self.cluster_changed(event=None)

    def run(self):
        i = 0
        try:
            while True:
                self._coordinator.heartbeat()
                self._coordinator.run_watchers()
                i += 1
                time.sleep(self.heartbeat_interval)
        except Exception as e:
            LOG.exception('Stopping RUG coordinator for exception: %s', type(e))
        finally:
            self.stop()

    def stop(self):
        if self.is_leader:
            try:
                self._coordinator.stand_down_group_leader(self.group)
            except tooz.NotImplemented:
                pass
        self._coordinator.leave_group(self.group).get()

    @property
    def members(self):
        return self._coordinator.get_members(self.group).get()

    @property
    def is_leader(self):
        return self._coordinator.get_leader(self.group).get() == self.host_id

    def cluster_changed(self, event):
        """Event callback to be called by tooz on membership changes"""
        LOG.debug('Broadcasting cluster changed event to trigger rebalance. '
                  'members=%s' % self.members)
        e = ak_event.Event(
            tenant_id='*',
            router_id='*',
            crud=ak_event.REBALANCE,
            body={'members': self.members}
        )
        self._queue.put(('*', e))

def start(notification_queue):
    return RugCoordinator(notification_queue).run()



if __name__ == '__main__':
    import multiprocessing
    q = multiprocessing.Queue()

    coord = RugCoordinator(q)
    coord.run()

