# Copyright 2015 Akanda, Inc
#
# Author: Akanda, Inc
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

import copy
import mock
import time

from six.moves import range
from astara.pez import pool as ak_pool
from astara.test.unit import base


class MockInstance(object):
    id = 'fake_instace_uuid'
    name = 'fake_name'
    status = ak_pool.ACTIVE


class PoolManagerTest(base.RugTestBase):
    def setUp(self):
        self.image_uuid = 'fake_image'
        self.flavor = 'fake_flavor'
        self.mgt_net_id = 'fake_mgt_net_id'
        self.pool_size = 3
        self.resource = 'router'
        super(PoolManagerTest, self).setUp()
        self.pool_manager = ak_pool.PezPoolManager(
            self.image_uuid,
            self.flavor,
            self.pool_size,
            self.mgt_net_id,
        )

    def _create_pool(self, num=3, status=ak_pool.ACTIVE):
        pool = [MockInstance() for i in range(0, num)]
        [setattr(p, 'status', status) for p in pool]
        return {self.resource: pool}

    @mock.patch('astara.pez.pool.PezPoolManager.delete_instance')
    def test__check_err_instances(self, mock_delete):
        pool = self._create_pool()
        pool[self.resource][1].id = 'errored_instance_id'
        pool[self.resource][1].status = ak_pool.ERROR
        deleting_instance = copy.copy(pool[self.resource][1])
        deleting_instance.status = ak_pool.DELETING
        mock_delete.return_value = deleting_instance
        self.pool_manager._check_err_instances(pool)
        self.assertIn(deleting_instance, pool[self.resource])
        mock_delete.assert_called_with('errored_instance_id')

    def test__check_del_instances(self):
        self.time_patch.stop()
        pool = self._create_pool(num=1, status=ak_pool.DELETING)
        self.pool_manager.delete_timeout = .01
        res = self.pool_manager._check_del_instances(pool)

        # deletion hasn't timed out yet

        self.assertEqual(0, len(res))
        # the deleting instance is added to the counter
        self.assertIn(
            pool[self.resource][0].id, self.pool_manager._delete_counters)

        # A stuck instance is reported back as such
        time.sleep(.02)
        res = self.pool_manager._check_del_instances(pool)
        self.assertIn(pool[self.resource][0], res)

        # once an instance is completely deleted, its counter is removed
        self.pool_manager._check_del_instances({self.resource: []})
        self.assertNotIn(
            pool[self.resource][0], self.pool_manager._delete_counters)
