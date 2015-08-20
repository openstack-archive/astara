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

import uuid

from akanda.rug.test.unit.db import base


class TestDBDebugModes(base.DbTestCase):
    def test_global_debug(self):
        self.dbapi.enable_global_debug()
        enabled, reason = self.dbapi.global_debug()
        self.assertTrue(enabled)
        self.assertIsNone(None)

        self.dbapi.disable_global_debug()
        enabled, reason = self.dbapi.global_debug()
        self.assertFalse(enabled)
        self.assertIsNone(reason)

    def test_global_debug_with_reason(self):
        self.dbapi.enable_global_debug(reason='foo')
        enabled, reason = self.dbapi.global_debug()
        self.assertTrue(enabled)
        self.assertEqual(reason, 'foo')

        self.dbapi.disable_global_debug()
        enabled, reason = self.dbapi.global_debug()
        self.assertFalse(enabled)
        self.assertIsNone(reason)

    def test_resource_debug(self):
        r_id = uuid.uuid4().hex
        self.dbapi.enable_resource_debug(
            resource_uuid=r_id)
        enabled, reason = self.dbapi.resource_in_debug(
            resource_uuid=r_id)
        self.assertTrue(enabled)
        self.assertIsNone(reason)
        self.dbapi.resource_in_debug('foo_resource')

    def test_resource_debug_with_reason(self):
        r_id = uuid.uuid4().hex
        self.dbapi.enable_resource_debug(
            resource_uuid=r_id, reason='foo')
        enabled, reason = self.dbapi.resource_in_debug(
            resource_uuid=r_id)
        self.assertTrue(enabled)
        self.assertEqual(reason, 'foo')

    def test_resources_in_debug(self):
        r_ids = [uuid.uuid4().hex for i in range(1, 3)]
        for r_id in r_ids:
            self.dbapi.enable_resource_debug(
                resource_uuid=r_id, reason='resource %s is broken' % r_id)
        for debug_r_id, reason in self.dbapi.resources_in_debug():
            self.assertIn(debug_r_id, r_ids)
            self.assertEqual(reason, 'resource %s is broken' % debug_r_id)

    def test_tenant_debug(self):
        t_id = uuid.uuid4().hex
        self.dbapi.enable_tenant_debug(
            tenant_uuid=t_id)
        enabled, reason = self.dbapi.tenant_in_debug(
            tenant_uuid=t_id)
        self.assertTrue(enabled)
        self.assertIsNone(reason)
        self.dbapi.tenant_in_debug('foo_tenant')

    def test_tenant_debug_with_reason(self):
        t_id = uuid.uuid4().hex
        self.dbapi.enable_tenant_debug(
            tenant_uuid=t_id, reason='foo')
        enabled, reason = self.dbapi.tenant_in_debug(
            tenant_uuid=t_id)
        self.assertTrue(enabled)
        self.assertEqual(reason, 'foo')

    def test_tenants_in_debug(self):
        t_ids = [uuid.uuid4().hex for i in range(1, 3)]
        for t_id in t_ids:
            self.dbapi.enable_tenant_debug(
                tenant_uuid=t_id, reason='tenant %s is broken' % t_id)
        for debug_t_id, reason in self.dbapi.tenants_in_debug():
            self.assertIn(debug_t_id, t_ids)
            self.assertEqual(reason, 'tenant %s is broken' % debug_t_id)
