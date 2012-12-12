from novaclient.v1_1 import client


class Nova(object):
    def __init__(self, conf):
        self.conf = conf
        self.client = client.Client(
            conf.admin_user,
            conf.admin_password,
            conf.admin_tenant_name,
            auth_url=conf.auth_url,
            auth_system=conf.auth_strategy,
            region_name=conf.auth_region)

    def create_router_instance(self, router):
        ports = [router.management_port, router.external_port]
        ports.extend(router.internal_ports)
        nics = [{'net-id': p.network_id, 'v4-fixed-ip':'', 'port-id': p.id}
                for p in ports]

        server = self.client.servers.create(
            'ak-' + router.id,
            image=self.conf.router_image_uuid,
            flavor=self.conf.router_instance_flavor,
            nics=nics)

    def get_instance(self, router):
        instances = self.client.servers.list(
            search_opts=dict(name='ak-' + router.id))

        if instances:
            return instances[0]
        else:
            return None

    def get_router_instance_status(self, router):
        instance = self.get_instance(router)
        if instance:
            return instance.status
        else:
            return None

    def destroy_router_instance(self, router):
        instance = self.get_instance(router)
        if instance:
            self.client.servers.delete(instance.id)

    def reboot_router_instance(self, router):
        instance = self.get_instance(router)
        if instance:
            if 'BUILD' in instance.status:
                return

            self.client.servers.delete(instance.id)

        self.create_router_instance(router)
