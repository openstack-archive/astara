
from astara.test.functional import base


class AstaraApplianceInstanceTest(base.AstaraFunctionalBase):
    """Basic tests to ensure a service instance and its associated router is
    alive and well.
    """
    def setUp(self):
        super(AstaraApplianceInstanceTest, self).setUp()
        # ensure the devstack spawned router instance becomes active before
        # starting to run any test cases. this in itself is a test that
        # devstack produced a functional router.
        self.assert_router_is_active()

    def test_appliance_is_alive(self):
        router_uuid = self.config['akanda_test_router_uuid']
        self.assertTrue(
            self.ak_client.is_alive(
                host=self.get_management_address(router_uuid),
                port=self.config['appliance_api_port'],
            ),
        )
