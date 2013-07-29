import mock
import unittest2 as unittest

from akanda.rug import manager


class TestManager(unittest.TestCase):
    def test_get_management_address(self):
        with mock.patch.object(manager.cfg, 'CONF') as conf:
            conf.management_prefix = 'fdca:3ba5:a17a:acda::/64'

            router = mock.Mock()
            router.management_port.mac_address = 'fa:16:3e:aa:dc:98'

            self.assertEqual(
                'fdca:3ba5:a17a:acda:f816:3eff:feaa:dc98',
                manager._get_management_address(router)
            )
