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


import uuid

import mock
from six.moves import range
from oslo_config import cfg
import unittest2 as unittest

from astara import scheduler


class TestScheduler(unittest.TestCase):

    def test_invalid_num_workers(self):
        cfg.CONF.num_worker_processes = 0
        self.assertRaises(
            ValueError,
            scheduler.Scheduler, mock.Mock)

    @mock.patch('multiprocessing.Process')
    def test_creating_workers(self, process):
        cfg.CONF.num_worker_processes = 2
        s = scheduler.Scheduler(mock.Mock)
        self.assertEqual(2, len(s.workers))

    @mock.patch('multiprocessing.Process')
    @mock.patch('multiprocessing.JoinableQueue')
    def test_stop(self, process, queue):
        cfg.CONF.num_worker_processes = 2
        s = scheduler.Scheduler(mock.Mock)
        s.stop()
        for w in s.workers:
            self.assertEqual(
                w['queue'].put.call_args_list,
                [mock.call(None), mock.call(None)]  # one put for each worker
            )
            self.assertEqual(w['queue'].close.call_count, 2)
            self.assertEqual(w['worker'].join.call_count, 2)


class TestDispatcher(unittest.TestCase):

    def setUp(self):
        super(TestDispatcher, self).setUp()
        self.workers = range(5)
        self.d = scheduler.Dispatcher(self.workers)

    def _mk_uuid(self, i):
        # Creates a well-known UUID
        return str(uuid.UUID(fields=(1, 2, 3, 4, 5, i)))

    def test_pick(self):
        for i in range(len(self.workers)):
            router_id = self._mk_uuid(i)
            self.assertEqual(
                [i],
                self.d.pick_workers(router_id),
                'Incorrect index for %s' % router_id,
            )

    def test_pick_none(self):
        router_id = None
        self.assertEqual(
            [],
            self.d.pick_workers(router_id),
            'Found a router for None',
        )

    def test_pick_with_spaces(self):
        for i in range(len(self.workers)):
            router_id = ' %s ' % self._mk_uuid(i)
            self.assertEqual(
                [i],
                self.d.pick_workers(router_id),
                'Incorrect index for %s' % router_id,
            )

    def test_pick_invalid(self):
        for i in range(len(self.workers)):
            router_id = self._mk_uuid(i) + 'Z'
            self.assertEqual(
                [],
                self.d.pick_workers(router_id),
                'Found unexpected worker for %r' % router_id,
            )

    def test_wildcard(self):
        self.assertEqual(
            self.workers,
            self.d.pick_workers('*'),
            'wildcard dispatch failed',
        )

    def test_error(self):
        self.assertEqual(
            self.workers,
            self.d.pick_workers('error'),
            'error dispatch failed',
        )
