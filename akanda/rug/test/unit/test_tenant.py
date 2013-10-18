import mock
import unittest2 as unittest

from akanda.rug import event
from akanda.rug import tenant


class TestTenantRouterManager(unittest.TestCase):

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def setUp(self, quantum_client):
        super(TestTenantRouterManager, self).setUp()

        self.vm_mgr = mock.patch('akanda.rug.vm_manager.VmManager').start()
        self.addCleanup(mock.patch.stopall)
        self.notifier = mock.Mock()
        self.trm = tenant.TenantRouterManager(
            '1234',
            notify_callback=self.notifier,
        )
        # Establish a fake default router for the tenant for tests
        # that try to use it. We mock out the class above to avoid
        # errors instantiating the client without enough config
        # settings, but we have to attach to the mock instance created
        # when we set the return value for get_router_for_tenant().
        client = self.trm.quantum
        self.default_router = mock.MagicMock(name='default_router')
        self.default_router.configure_mock(id='9ABC')
        client.get_router_for_tenant.return_value = self.default_router

    def test_new_router(self):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sm = self.trm.get_state_machines(msg)[0]
        self.assertEqual(sm.router_id, '5678')
        self.assertIn('5678', self.trm.state_machines)

    def test_default_router(self):
        msg = event.Event(
            tenant_id='1234',
            router_id=None,
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sm = self.trm.get_state_machines(msg)[0]
        self.assertEqual(sm.router_id, self.default_router.id)
        self.assertIn(self.default_router.id, self.trm.state_machines)

    def test_all_routers(self):
        self.trm.state_machines = dict((str(i), i) for i in range(5))
        msg = event.Event(
            tenant_id='1234',
            router_id='*',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sms = self.trm.get_state_machines(msg)
        self.assertEqual(5, len(sms))

    @mock.patch('akanda.rug.state.Automaton')
    def test_existing_router(self, automaton):

        def side_effect(*args, **kwargs):
            return mock.Mock(*args, **kwargs)

        automaton.side_effect = side_effect
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        # First time creates...
        sm1 = self.trm.get_state_machines(msg)[0]
        # Second time should return the same objects...
        sm2 = self.trm.get_state_machines(msg)[0]
        self.assertIs(sm1, sm2)
        self.assertIs(sm1.queue, sm2.queue)

    @mock.patch('akanda.rug.state.Automaton')
    def test_existing_router_of_many(self, automaton):

        def side_effect(*args, **kwargs):
            return mock.Mock(*args, **kwargs)

        automaton.side_effect = side_effect
        sms = {}
        for router_id in ['5678', 'ABCD', 'EFGH']:
            msg = event.Event(
                tenant_id='1234',
                router_id=router_id,
                crud=event.CREATE,
                body={'key': 'value'},
            )
            # First time creates...
            sm1 = self.trm.get_state_machines(msg)[0]
            sms[router_id] = sm1
        # Second time should return the same objects...
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sm2 = self.trm.get_state_machines(msg)[0]
        self.assertIs(sm2, sms['5678'])

    def test_delete_router(self):
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_router('1234')
        self.assertNotIn('1234', self.trm.state_machines)

    def test_delete_default_router(self):
        self.trm._default_router_id = '1234'
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_router('1234')
        self.assertNotIn('1234', self.trm.state_machines)
        self.assertIs(None, self.trm._default_router_id)

    def test_delete_not_default_router(self):
        self.trm._default_router_id = 'abcd'
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_router('1234')
        self.assertEqual('abcd', self.trm._default_router_id)

    def test_no_update_deleted_router(self):
        self.trm._default_router_id = 'abcd'
        self.trm.state_machines['5678'] = mock.Mock()
        self.trm._delete_router('5678')
        self.assertEqual(self.trm.state_machines.values(), [])
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sms = self.trm.get_state_machines(msg)
        self.assertEqual(sms, [])
        self.assertIn('5678', self.trm.state_machines.deleted)

    def test_deleter_callback(self):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sm = self.trm.get_state_machines(msg)[0]
        self.assertIn('5678', self.trm.state_machines)
        sm._do_delete()
        self.assertNotIn('5678', self.trm.state_machines)

    def test_report_bandwidth(self):
        notifications = []
        self.notifier.side_effect = notifications.append
        self.trm._report_bandwidth(
            '5678',
            [{'name': 'a',
              'value': 1,
              },
             {'name': 'b',
              'value': 2,
              }],
        )
        n = notifications[0]
        self.assertEqual('1234', n['tenant_id'])
        self.assertIn('5678', n['router_id'])
        self.assertIn('timestamp', n)
        self.assertEqual('akanda.bandwidth.used', n['event_type'])
        self.assertIn('a', n['payload'])
        self.assertIn('b', n['payload'])
