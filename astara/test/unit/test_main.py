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

from astara import main
from astara import notifications as ak_notifications
from astara.test.unit import base


@mock.patch('astara.main.neutron_api')
@mock.patch('astara.main.multiprocessing')
@mock.patch('astara.main.notifications')
@mock.patch('astara.main.scheduler')
@mock.patch('astara.main.populate')
@mock.patch('astara.main.health')
class TestMainPippo(base.RugTestBase):
    def test_shuffle_notifications(self, health, populate, scheduler,
                                   notifications, multiprocessing,
                                   neutron_api):
        queue = mock.Mock()
        queue.get.side_effect = [
            ('9306bbd8-f3cc-11e2-bd68-080027e60b25', 'message'),
            KeyboardInterrupt,
        ]
        sched = scheduler.Scheduler.return_value
        main.shuffle_notifications(queue, sched)
        sched.handle_message.assert_called_once_with(
            '9306bbd8-f3cc-11e2-bd68-080027e60b25',
            'message'
        )

    def test_shuffle_notifications_error(
            self, health, populate, scheduler, notifications,
            multiprocessing, neutron_api):
        queue = mock.Mock()
        queue.get.side_effect = [
            ('9306bbd8-f3cc-11e2-bd68-080027e60b25', 'message'),
            RuntimeError,
            KeyboardInterrupt,
        ]
        sched = scheduler.Scheduler.return_value
        main.shuffle_notifications(queue, sched)
        sched.handle_message.assert_called_once_with(
            '9306bbd8-f3cc-11e2-bd68-080027e60b25', 'message'
        )

    @mock.patch('astara.main.shuffle_notifications')
    def test_ensure_local_service_port(self, shuffle_notifications, health,
                                       populate, scheduler, notifications,
                                       multiprocessing, neutron_api):
        main.main(argv=self.argv)
        neutron = neutron_api.Neutron.return_value
        neutron.ensure_local_service_port.assert_called_once_with()

    @mock.patch('astara.main.shuffle_notifications')
    def test_ceilometer_disabled(self, shuffle_notifications, health,
                                 populate, scheduler, notifications,
                                 multiprocessing, neutron_api):
        self.test_config.config(enabled=False, group='ceilometer')
        notifications.Publisher = mock.Mock(spec=ak_notifications.Publisher)
        notifications.NoopPublisher = mock.Mock(
            spec=ak_notifications.NoopPublisher)
        main.main(argv=self.argv)
        self.assertEqual(len(notifications.Publisher.mock_calls), 0)
        self.assertEqual(len(notifications.NoopPublisher.mock_calls), 2)

    @mock.patch('astara.main.shuffle_notifications')
    def test_ceilometer_enabled(self, shuffle_notifications, health,
                                populate, scheduler, notifications,
                                multiprocessing, neutron_api):
        self.test_config.config(enabled=True, group='ceilometer')
        notifications.Publisher = mock.Mock(spec=ak_notifications.Publisher)
        notifications.NoopPublisher = mock.Mock(
            spec=ak_notifications.NoopPublisher)
        main.main(argv=self.argv)
        self.assertEqual(len(notifications.Publisher.mock_calls), 2)
        self.assertEqual(len(notifications.NoopPublisher.mock_calls), 0)
