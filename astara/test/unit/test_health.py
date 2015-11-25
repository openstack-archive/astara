# Copyright (c) 2015 Akanda, Inc. All Rights Reserved.
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

from akanda.rug import event
from akanda.rug import health
from akanda.rug.test.unit import base


class BreakLoop(Exception):
    pass


class HealthTest(base.RugTestBase):
    @mock.patch('time.sleep')
    def test_health_inspector(self, fake_sleep):
        fake_scheduler = mock.Mock(
            handle_message=mock.Mock()
        )

        # raise the exception to break out of the while loop.
        fake_scheduler.handle_message.side_effect = BreakLoop()
        try:
            health._health_inspector(fake_scheduler)
        except BreakLoop:
            pass

        exp_res = event.Resource(
            id='*',
            tenant_id='*',
            driver='*',
        )
        exp_event = event.Event(
            resource=exp_res,
            crud=event.POLL,
            body={},
        )
        fake_scheduler.handle_message.assert_called_with('*', exp_event)
