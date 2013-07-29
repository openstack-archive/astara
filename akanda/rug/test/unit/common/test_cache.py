import unittest2 as unittest

from akanda.rug.common import cache


class FakeModel:
    def __init__(self, id_, **kwargs):
        self.id = id_
        self.__dict__.update(kwargs)

    def __str__(self):
        return str(self.__dict__)


class TestCache(unittest.TestCase):
    def test_init(self):
        cache.RouterCache()

    def test_put(self):
        fake_router = FakeModel(
            'the_id',
            tenant_id='tenant_id',
            internal_ports=[FakeModel('port_id', network_id='net1')])

        c = cache.RouterCache()
        c.put(fake_router)

        self.assertEqual(c.cache, {'the_id': fake_router})
        self.assertEqual(c.router_by_tenant.keys(), ['tenant_id'])
        self.assertEqual(c.router_by_tenant_network.keys(), ['net1'])

    def test_remove(self):
        fake_router = FakeModel(
            'the_id',
            tenant_id='tenant_id',
            internal_ports=[FakeModel('port_id', network_id='net1')])

        c = cache.RouterCache()
        c.put(fake_router)
        c.remove(fake_router.id)
        del fake_router

        self.assertEqual(len(c.cache), 0)
        self.assertEqual(len(c.router_by_tenant), 0)
        self.assertEqual(len(c.router_by_tenant_network), 0)

    def test_remove_nonexistent(self):
        c = cache.RouterCache()
        c.remove('bad_id')
        self.assertEqual(len(c.cache), 0)
        self.assertEqual(len(c.router_by_tenant), 0)
        self.assertEqual(len(c.router_by_tenant_network), 0)

    def test_get(self):
        fake_router = FakeModel(
            'the_id',
            tenant_id='tenant_id',
            internal_ports=[FakeModel('port_id', network_id='net1')])

        c = cache.RouterCache()
        c.put(fake_router)

        self.assertEqual(c.get('the_id'), fake_router)
        self.assertEqual(c.get_by_tenant_id('tenant_id'), fake_router)

    def test_keys(self):
        fake_router1 = FakeModel(
            'the_id',
            tenant_id='tenant_id',
            internal_ports=[FakeModel('port_id', network_id='net1')])

        fake_router2 = FakeModel(
            'the_2nd',
            tenant_id='tenant_id2',
            internal_ports=[FakeModel('port_id', network_id='net2')])

        c = cache.RouterCache()
        c.put(fake_router1)
        c.put(fake_router2)

        self.assertItemsEqual(c.keys(), ['the_id', 'the_2nd'])

    def test_routers(self):
        fake_router1 = FakeModel(
            'the_id',
            tenant_id='tenant_id',
            internal_ports=[FakeModel('port_id', network_id='net1')])

        fake_router2 = FakeModel(
            'the_2nd',
            tenant_id='tenant_id2',
            internal_ports=[FakeModel('port_id', network_id='net2')])

        c = cache.RouterCache()
        c.put(fake_router1)
        c.put(fake_router2)

        self.assertItemsEqual(c.routers(), [fake_router1, fake_router2])
