import mock
import unittest2 as unittest

from akanda.rug import vm_manager
vm_manager.RETRY_DELAY = 0.4
vm_manager.BOOT_WAIT = 1


class TestVmManager(unittest.TestCase):
    def setUp(self):
        quantum_cls = mock.patch.object(vm_manager.quantum, 'Quantum').start()
        self.quantum = quantum_cls.return_value
        self.conf = mock.patch.object(vm_manager.cfg, 'CONF').start()
        self.conf.boot_timeout = 1
        self.conf.akanda_mgt_service_port = 5000
        self.addCleanup(mock.patch.stopall)

        self.log = mock.Mock()
        self.update_state_p = mock.patch.object(
            vm_manager.VmManager,
            'update_state'
        )

        self.mock_update_state = self.update_state_p.start()
        self.vm_mgr = vm_manager.VmManager('the_id', self.log)
        self.vm_mgr.router_obj = mock.Mock()

        self.next_state = None

        def next_state(*args, **kwargs):
            if self.next_state:
                self.vm_mgr.state = self.next_state
            return self.vm_mgr.state
        self.mock_update_state.side_effect = next_state

    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_update_state_is_alive(self, get_mgt_addr, router_api):
        self.update_state_p.stop()
        get_mgt_addr.return_value = 'fe80::beef'
        router_api.is_alive.return_value = True

        self.assertEqual(self.vm_mgr.update_state(), vm_manager.UP)
        router_api.is_alive.assert_called_once_with('fe80::beef', 5000)

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_update_state_is_down(self, get_mgt_addr, router_api, sleep):
        self.update_state_p.stop()
        get_mgt_addr.return_value = 'fe80::beef'
        router_api.is_alive.return_value = False

        self.assertEqual(self.vm_mgr.update_state(), vm_manager.DOWN)
        router_api.is_alive.assert_has_calls([
            mock.call('fe80::beef', 5000),
            mock.call('fe80::beef', 5000),
            mock.call('fe80::beef', 5000)
        ])

    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_update_state_no_mgt_port(self, get_mgt_addr):
        self.update_state_p.stop()
        self.vm_mgr.router_obj.management_port = None
        self.assertEqual(self.vm_mgr.update_state(), vm_manager.DOWN)
        self.assertFalse(get_mgt_addr.called)

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.api.nova.Nova')
    def test_boot_success(self, nova_cls, sleep):
        self.next_state = vm_manager.UP
        self.vm_mgr.boot()
        self.assertEqual(self.vm_mgr.state, vm_manager.UP)
        nova_cls.return_value.reboot_router_instance.assert_called_once_with(
            self.vm_mgr.router_obj
        )

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.api.nova.Nova')
    def test_boot_fail(self, nova_cls, sleep):
        self.next_state = vm_manager.DOWN
        self.vm_mgr.boot()
        self.assertEqual(self.vm_mgr.state, vm_manager.DOWN)
        nova_cls.return_value.reboot_router_instance.assert_called_once_with(
            self.vm_mgr.router_obj
        )
        self.log.error.assert_called_once_with(mock.ANY, 1)

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.api.nova.Nova')
    def test_stop_success(self, nova_cls, sleep):
        self.vm_mgr.state = vm_manager.UP
        nova_cls.return_value.get_router_instance_status.return_value = None
        self.vm_mgr.stop()
        self.assertEqual(self.vm_mgr.state, vm_manager.DOWN)
        nova_cls.return_value.destroy_router_instance.assert_called_once_with(
            self.vm_mgr.router_obj
        )

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.api.nova.Nova')
    def test_stop_fail(self, nova_cls, sleep):
        self.vm_mgr.state = vm_manager.UP
        nova_cls.return_value.get_router_instance_status.return_value = 'UP'
        self.vm_mgr.stop()
        self.assertEqual(self.vm_mgr.state, vm_manager.UP)
        nova_cls.return_value.destroy_router_instance.assert_called_once_with(
            self.vm_mgr.router_obj
        )
        self.log.error.assert_called_once_with(mock.ANY, 1)

    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_configure_success(self, config, get_mgt_addr, router_api):
        get_mgt_addr.return_value = 'fe80::beef'
        rtr = mock.sentinel.router

        self.quantum.get_router_detail.return_value = rtr

        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = True
            self.vm_mgr.configure()

            interfaces = router_api.get_interfaces.return_value

            verify.assert_called_once_with(rtr, interfaces)
            config.assert_called_once_with(self.quantum, rtr, interfaces)
            router_api.update_config.assert_called_once_with(
                'fe80::beef',
                5000,
                config.return_value
            )
            self.assertEqual(self.vm_mgr.state, vm_manager.CONFIGURED)

    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    def test_configure_mismatched_interfaces(self, get_mgt_addr, router_api):
        get_mgt_addr.return_value = 'fe80::beef'
        rtr = mock.sentinel.router

        self.quantum.get_router_detail.return_value = rtr

        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = False
            self.vm_mgr.configure()

            interfaces = router_api.get_interfaces.return_value

            verify.assert_called_once_with(rtr, interfaces)

            self.assertFalse(router_api.update_config.called)
            self.assertEqual(self.vm_mgr.state, vm_manager.RESTART)

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.vm_manager.router_api')
    @mock.patch('akanda.rug.vm_manager._get_management_address')
    @mock.patch('akanda.rug.api.configuration.build_config')
    def test_configure_failure(self, config, get_mgt_addr, router_api, sleep):
        get_mgt_addr.return_value = 'fe80::beef'
        rtr = {'id': 'the_id'}

        self.quantum.get_router_detail.return_value = rtr

        router_api.update_config.side_effect = Exception

        with mock.patch.object(self.vm_mgr, '_verify_interfaces') as verify:
            verify.return_value = True
            self.vm_mgr.configure()

            interfaces = router_api.get_interfaces.return_value

            verify.assert_called_once_with(rtr, interfaces)
            config.assert_called_once_with(self.quantum, rtr, interfaces)
            router_api.update_config.assert_has_calls([
                mock.call('fe80::beef', 5000, config.return_value),
                mock.call('fe80::beef', 5000, config.return_value),
                mock.call('fe80::beef', 5000, config.return_value),
            ])
            self.assertEqual(self.vm_mgr.state, vm_manager.UP)

    def test_ensure_cache(self):
        rtr = {'id': 'the_id'}

        self.quantum.get_router_detail.return_value = rtr

        self.vm_mgr._ensure_cache()
        self.assertFalse(self.quantum.get_router_detail.called)

        self.vm_mgr.router_obj = None
        self.vm_mgr._ensure_cache()
        self.assertTrue(self.quantum.get_router_detail.called)

    def test_verify_interfaces(self):
        rtr = mock.Mock()
        rtr.management_port.mac_address = 'a:b:c:d'
        rtr.external_port.mac_address = 'd:c:b:a'
        p = mock.Mock()
        p.mac_address = 'a:a:a:a'
        rtr.internal_ports = [p]

        interfaces = [
            {'lladdr': 'a:b:c:d'},
            {'lladdr': 'd:c:b:a'},
            {'lladdr': 'a:a:a:a'}
        ]

        self.assertTrue(self.vm_mgr._verify_interfaces(rtr, interfaces))

    def test_ensure_provider_ports(self):
        rtr = mock.Mock()
        rtr.id = 'id'
        rtr.management_port = None
        rtr.external_port = None

        self.vm_mgr._ensure_provider_ports(rtr)
        self.quantum.create_router_management_port.assert_called_once_with(
            'id'
        )

        self.assertEqual(self.vm_mgr._ensure_provider_ports(rtr), rtr)
        self.quantum.create_router_external_port.assert_called_once_with(rtr)
