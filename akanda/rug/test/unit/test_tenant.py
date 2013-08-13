import mock
import unittest2 as unittest

from akanda.rug import event
from akanda.rug import tenant


class TestTenantRouterManager(unittest.TestCase):

    def setUp(self):
        super(TestTenantRouterManager, self).setUp()
        self.trm = tenant.TenantRouterManager('1234')

    def test_new_router(self):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sm, inq = self.trm.get_state_machine(msg)
        self.assertEqual(sm.router_id, '5678')
        self.assertIn('5678', self.trm.state_machines)

    @mock.patch('akanda.rug.state.Automaton')
    def test_existing_router(self, automaton):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        # First time creates...
        sm1, inq1 = self.trm.get_state_machine(msg)
        # Second time should return the same objects...
        sm2, inq2 = self.trm.get_state_machine(msg)
        self.assertIs(sm1, sm2)
        self.assertIs(inq1, inq2)

    def test_delete_router(self):
        self.trm.state_machines['1234'] = {
            'sm': mock.Mock(),
            'inq': mock.Mock(),
        }
        self.trm._delete_router('1234')
        self.assertNotIn('1234', self.trm.state_machines)

    def test_deleter_callback(self):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        sm, inq = self.trm.get_state_machine(msg)
        self.assertIn('5678', self.trm.state_machines)
        sm.delete_callback()
        self.assertNotIn('5678', self.trm.state_machines)
