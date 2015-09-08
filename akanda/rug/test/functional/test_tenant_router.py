
import datetime
import time

from akanda.rug.test.functional import base


class TestAkandaRouter(base.AkandaFunctionalBase):
    @classmethod
    def setUpClass(cls):
        super(TestAkandaRouter, cls).setUpClass()
        cls.tenant = cls.get_tenant()
        cls.neutronclient = cls.tenant.clients.neutronclient

    def test_get_router_by_creating_a_net(self):
        """
        Test to ensure that in a clean tenant, when a network is created,
        /w an ipv6 subnet, a neutron router and an akanda router will be
        created as well.
        """
        network, router = self.tenant.setup_default_tenant_networking()
        self.assert_router_is_active(router['id'])

        # refresh router ref now that its active
        router = self.neutronclient.show_router(router['id'])['router']

        # for each subnet that was created during setup, ensure we have a
        # router interface added
        ports = self.neutronclient.list_ports()['ports']
        subnets = self.neutronclient.list_subnets(network_id=network['id'])
        subnets = subnets['subnets']
        self.assertEquals(len(ports), len(subnets))
        for port in ports:
            self.assertEquals(port['device_owner'], 'network:router_interface')
            self.assertEquals(port['device_id'], router['id'])
            self.assertEquals(
                sorted([subnet['id'] for subnet in subnets]),
                sorted([fip['subnet_id'] for fip in port['fixed_ips']])
            )

        self.ping_router_mgt_address(router['id'])

        # Ensure that if we destroy the nova instance, the RUG will rebuild
        # the router with a new instance.
        # This could live in a separate test case but it'd require the
        # above as setup, so just piggyback on it.

        old_server = self.get_router_appliance_server(router['id'])

        # sleep for 2x the config_timeout to ensure, if the first config update
        # timesout we at least give it another try befre deleting and
        # continuing.
        time.sleep(120)

        print 'deleting server @ %s' % str(datetime.datetime.now())
        self.admin_clients.novaclient.servers.delete(old_server.id)

        # we need to sleep for the health_check_period to allow rug to notice
        # the instance is gone and trigger the rebuild. default is currently
        # 60s but we update it to 10s in devstack.
        time.sleep(10)

        # look for the new server, retry giving rug time to do its thing.
        new_server = self.get_router_appliance_server(
            router['id'], retries=120, wait_for_active=True)
        self.assertNotEqual(old_server.id, new_server.id)

        # routers report as ACTIVE initially (LP: #1491673)
        time.sleep(2)

        self.assert_router_is_active(router['id'])
        self.ping_router_mgt_address(router['id'])
