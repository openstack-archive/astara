import mock
import unittest2 as unittest

from akanda.rug import event
from akanda.rug import tenant


class TestTenantRouterManager(unittest.TestCase):

    def setUp(self):
        super(TestTenantRouterManager, self).setUp()
        self.trm = tenant.TenantRouterManager('1234')

    @mock.patch('akanda.rug.state.Automaton')
    def test_new_router(self, automaton):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.trm.handle_message(msg)
        self.assertIn('5678', self.trm.state_machines)
        automaton.assert_called_with(
            router_id='5678',
            delete_callback=self.trm._delete_router,
        )

    def test_delete_router(self):
        self.trm.state_machines['1234'] = mock.Mock()
        self.trm._delete_router('1234')
        self.assertNotIn('1234', self.trm.state_machines)
