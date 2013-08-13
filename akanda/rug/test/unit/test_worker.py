import mock
import unittest2 as unittest

from akanda.rug import event
from akanda.rug import worker


class TestWorker(unittest.TestCase):

    def setUp(self):
        super(TestWorker, self).setUp()
        self.w = worker.Worker(1)

    @mock.patch('akanda.rug.tenant.TenantRouterManager')
    def test_new_router(self, automaton):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.w.handle_message('1234', {'key': 'value'})
        self.assertIn('1234', self.w.tenant_managers)
        automaton.assert_called_with(
            tenant_id='1234',
        )
