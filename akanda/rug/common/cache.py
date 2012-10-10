import logging
import weakref

LOG = logging.getLogger(__name__)


class RouterCache(object):
    def __init__(self):
        self.cache = {}
        self.router_by_tenant = weakref.WeakValueDictionary()
        self.router_by_tenant_network = weakref.WeakValueDictionary()

    def put(self, router):
        self.cache[router.id] = router
        self.router_by_tenant[router.tenant_id] = router

        for port in router.internal_ports:
            self.router_by_tenant_network[port.network_id] = router

    def remove(self, router_id):
        try:
            del self.cache[router_id]
        except KeyError:
            pass

    def get(self, key, default=None):
        return self.cache.get(key, default)

    def get_by_tenant_id(self, tenant_id):
        return self.router_by_tenant.get(tenant_id)

    def keys(self):
        return self.cache.keys()

    def routers(self):
        return self.cache.values()
