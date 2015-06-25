# Copyright 2015 Akanda, Inc.
#
# Author: Akanda, Inc.
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

import time

from akanda.rug import event as ak_event
from akanda.rug.common.i18n import _

from oslo_config import cfg
from oslo_log import log

import tooz
from tooz import coordination as tz_coordination


LOG = log.getLogger(__name__)
CONF = cfg.CONF


COORD_OPTS = [
    cfg.BoolOpt('enabled', default=True,
                help=_('Whether to use an external coordination service to '
                       'a cluster of akanda-rug nodes. This may be disabled '
                       'for akanda-rug node environments.')),
    cfg.StrOpt('url',
               default='memcached://localhost:11211',
               help=_('URL of suppoted coordination service')),
    cfg.StrOpt('group_id', default='akanda.rug',
               help=_('ID of coordination group to join.')),
    cfg.IntOpt('heartbeat_interval', default=1,
               help=_('Interval (in seconds) for cluster heartbeats')),
]
CONF.register_group(cfg.OptGroup(name='coordination'))
CONF.register_opts(COORD_OPTS, group='coordination')


class InvalidEventType(Exception):
    pass


class RugCoordinator(object):
    def __init__(self, notifications_queue):
        self._queue = notifications_queue
        self.host = CONF.host
        self.url = CONF.coordination.url
        self.group = CONF.coordination.group_id
        self.heartbeat_interval = CONF.coordination.heartbeat_interval
        self._coordinator = None
        self.start()

    def start(self):
        LOG.info(
            'Starting RUG coordinator process for host %s on %s' %
            (self.host, self.url))
        self._coordinator = tz_coordination.get_coordinator(
            self.url, self.host)
        self._coordinator.start()

        try:
            self._coordinator.create_group(self.group).get()
        except tooz.coordination.GroupAlreadyExist:
            pass

        try:
            self._coordinator.join_group(self.group).get()
            self._coordinator.heartbeat()
        except tooz.coordination.MemberAlreadyExist:
            pass

        self._coordinator.watch_join_group(self.group, self.cluster_changed)
        self._coordinator.watch_leave_group(self.group, self.cluster_changed)
        self._coordinator.heartbeat()
        LOG.debug("Sending initial event changed for members; %s" %
                  self.members)
        self.cluster_changed(event=None)

    def run(self):
        try:
            while True:
                self._coordinator.heartbeat()
                self._coordinator.run_watchers()
                time.sleep(self.heartbeat_interval)
        except Exception as e:
            LOG.exception('Stopping RUG coordinator for exception: %s',
                          type(e))
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
        return self._coordinator.get_leader(self.group).get() == self.host

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
