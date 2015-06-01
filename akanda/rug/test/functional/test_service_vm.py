
from akanda.rug.test.functional import base

import time

class AkandaApplianceVMTest(base.AkandaFunctionalBase):
    """Basic tests to ensure a service VM and its associated router is alive
    and well.
    """
    def test_appliance_is_alive(self):
        # might be the first test running after devstack completes, give the
        # vm time to boot and configure
        # TODO(adam)g: We can replace this with tempest_lib waiter that waits
        # for router status to be active
        time.sleep(60)
        self.assertTrue(
            self.ak_client.is_alive(
                host=self.management_address,
                port=self.config['appliance_api_port'],
            ),
        )
