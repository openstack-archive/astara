import uuid

from akanda.rug.test.unit.db import base


class TestDBDebugModes(base.DbTestCase):
    def test_global_debug(self):
        self.dbapi.enable_global_debug()
        enabled, reason = self.dbapi.global_debug()
        self.assertEqual(enabled, True)
        self.assertEqual(reason, None)

        self.dbapi.disable_global_debug()
        enabled, reason = self.dbapi.global_debug()
        self.assertEqual(enabled, False)
        self.assertEqual(reason, None)

    def test_global_debug_with_reason(self):
        self.dbapi.enable_global_debug(reason='foo')
        enabled, reason = self.dbapi.global_debug()
        self.assertEqual(enabled, True)
        self.assertEqual(reason, 'foo')

        self.dbapi.disable_global_debug()
        enabled, reason = self.dbapi.global_debug()
        self.assertEqual(enabled, False)
        self.assertEqual(reason, None)

    def test_router_debug(self):
        r_id = uuid.uuid4().hex
        self.dbapi.enable_router_debug(
            router_uuid=r_id)
        enabled, reason = self.dbapi.router_in_debug(
            router_uuid=r_id)
        self.assertEqual(enabled, True)
        self.assertEqual(reason, None)
        self.dbapi.router_in_debug('foo_router')

    def test_router_debug_with_reason(self):
        r_id = uuid.uuid4().hex
        self.dbapi.enable_router_debug(
            router_uuid=r_id, reason='foo')
        enabled, reason = self.dbapi.router_in_debug(
            router_uuid=r_id)
        self.assertEqual(enabled, True)
        self.assertEqual(reason, 'foo')

    def test_routers_in_debug(self):
        r_ids = [uuid.uuid4().hex for i in range(1, 3)]
        for r_id in r_ids:
            self.dbapi.enable_router_debug(
                router_uuid=r_id, reason='router %s is broken' % r_id)
        for debug_r_id, reason in self.dbapi.routers_in_debug():
            self.assertIn(debug_r_id, r_ids)
            self.assertEqual(reason, 'router %s is broken' % debug_r_id)

    def test_tenant_debug(self):
        t_id = uuid.uuid4().hex
        self.dbapi.enable_tenant_debug(
            tenant_uuid=t_id)
        enabled, reason = self.dbapi.tenant_in_debug(
            tenant_uuid=t_id)
        self.assertEqual(enabled, True)
        self.assertEqual(reason, None)
        self.dbapi.tenant_in_debug('foo_tenant')

    def test_tenant_debug_with_reason(self):
        t_id = uuid.uuid4().hex
        self.dbapi.enable_tenant_debug(
            tenant_uuid=t_id, reason='foo')
        enabled, reason = self.dbapi.tenant_in_debug(
            tenant_uuid=t_id)
        self.assertEqual(enabled, True)
        self.assertEqual(reason, 'foo')

    def test_tenants_in_debug(self):
        t_ids = [uuid.uuid4().hex for i in range(1, 3)]
        for t_id in t_ids:
            self.dbapi.enable_tenant_debug(
                tenant_uuid=t_id, reason='tenant %s is broken' % t_id)
        for debug_t_id, reason in self.dbapi.tenants_in_debug():
            self.assertIn(debug_t_id, t_ids)
            self.assertEqual(reason, 'tenant %s is broken' % debug_t_id)
