# Copyright 2014 DreamHost, LLC
#
# Author: DreamHost, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


import mock

from akanda.rug.test.unit import base
from akanda.rug.test.unit import fakes

from akanda.rug import populate
from akanda.rug import event
from akanda.rug.resource import Resource


class FakePopulateDriver(object):
    pre_populate_hook = mock.Mock()


class TestPrePopulateWorkers(base.RugTestBase):
    def setUp(self):
        super(TestPrePopulateWorkers, self).setUp()

    @mock.patch('akanda.rug.drivers.enabled_drivers')
    def test_pre_populate_with_resources(self, enabled_drivers):
        fake_scheduler = mock.Mock()
        fake_scheduler.handle_message = mock.Mock()
        fake_driver = fakes.fake_driver()
        fake_resources = [
            Resource(
                id='fake_resource_%s' % i,
                tenant_id='fake_tenant_%s' % i,
                driver=fake_driver.RESOURCE_NAME,
            ) for i in range(2)
        ]
        fake_driver.pre_populate_hook.return_value = fake_resources
        enabled_drivers.return_value = [fake_driver]
        populate._pre_populate_workers(fake_scheduler)
        for res in fake_resources:
            e = event.Event(resource=res, crud=event.POLL, body={})
            call = mock.call(res.tenant_id, e)
            self.assertIn(call, fake_scheduler.handle_message.call_args_list)

    @mock.patch('akanda.rug.drivers.enabled_drivers')
    def test_pre_populate_with_no_resources(self, enabled_drivers):
        fake_scheduler = mock.Mock()
        fake_scheduler.handle_message = mock.Mock()
        fake_driver = fakes.fake_driver()
        fake_driver.pre_populate_hook.return_value = []
        enabled_drivers.return_value = [fake_driver]
        populate._pre_populate_workers(fake_scheduler)
        self.assertFalse(fake_scheduler.handle_message.called)

    @mock.patch('threading.Thread')
    def test_pre_populate_workers(self, thread):
        sched = mock.Mock()
        t = populate.pre_populate_workers(sched)
        thread.assert_called_once_with(
            target=populate._pre_populate_workers,
            args=(sched,),
            name='PrePopulateWorkers'
        )
        self.assertEqual(
            t.mock_calls,
            [mock.call.setDaemon(True), mock.call.start()]
        )
