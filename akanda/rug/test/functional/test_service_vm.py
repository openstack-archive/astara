
from akanda.rug.test.functional import base


class AkandaApplianceVMTest(base.AkandaFunctionalBase):
    """Basic tests to ensure a service VM and its associated router is alive
    and well.
    """
    def test_appliance_is_alive(self):
        self.assertTrue(
            self.ak_client.is_alive(
                host=self.management_address,
                port=self.config['appliance_api_port'],
            ),
        )
