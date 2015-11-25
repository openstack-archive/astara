
from astara.test.functional import base


class AkandaApplianceInstanceTest(base.AkandaFunctionalBase):
    """Basic tests to ensure a service instance and its associated router is
    alive and well.
    """
    def setUp(self):
        super(AkandaApplianceInstanceTest, self).setUp()
        # ensure the devstack spawned router instance becomes active before
        # starting to run any test cases. this in itself is a test that
        # devstack produced a functional router.
        self.assert_router_is_active()

    def test_appliance_is_alive(self):
        self.assertTrue(
            self.ak_client.is_alive(
                host=self.management_address,
                port=self.config['appliance_api_port'],
            ),
        )
