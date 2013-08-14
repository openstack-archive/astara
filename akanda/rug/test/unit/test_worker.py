import mock

import unittest2 as unittest

from akanda.rug import event
from akanda.rug import worker


class TestWorker(unittest.TestCase):

    def setUp(self):
        super(TestWorker, self).setUp()
        self.w = worker.Worker(1)

    def tearDown(self):
        self.w._shutdown()
        super(TestWorker, self).tearDown()

    @mock.patch('akanda.rug.api.quantum.Quantum')
    def test_new_router(self, quantum):
        msg = event.Event(
            tenant_id='1234',
            router_id='5678',
            crud=event.CREATE,
            body={'key': 'value'},
        )
        self.w.handle_message('1234', msg)
        self.assertIn('1234', self.w.tenant_managers)
        trm = self.w.tenant_managers['1234']
        self.assertEqual('1234', trm.tenant_id)
