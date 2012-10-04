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
        nics = [{'net-id': p.network_id, 'v4-fixed-ip':'', 'port-id': p.id} for p in ports]

        server = self.client.servers.create(
            'ak-' + router.id,
            image=self.conf.router_image_uuid,
            flavor=self.conf.router_instance_flavor,
            nics=nics)

    def _get_instance_id(self, router_id):
        instances = self.client.servers.list(
            search_opts=dict(name='ak-' + router_id))

        if instances:
            return instances[0]
        else:
            return None

    def delete_router_instance(self, router):
        instance_id = self._get_instance_id(router.id)
        if instance_id:
            self.client.servers.delete(instance_id)

    def reboot_router_instance(self, router):
        instance_id = self._get_instance_id(router.id)
        if instance_id:
            self.client.servers.reboot(instance_id)
        else:
            self.create_router_instance(router)
