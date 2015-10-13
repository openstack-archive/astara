import mock

from Queue import Queue

from tooz import coordination as tz_coordination

from akanda.rug import coordination
from akanda.rug import event
from akanda.rug.test.unit import base


class TestRugCoordinator(base.RugTestBase):
    def get_fake_coordinator(self, url, member_id):
        return self.fake_coord

    def setUp(self):
        super(TestRugCoordinator, self).setUp()
        self.config(url='memcache://foo_cache', group='coordination')
        self.config(group_id='foo_coord_group', group='coordination')
        self.config(heartbeat_interval=9, group='coordination')
        self.config(host='foo_host')

        self.fake_coord = mock.MagicMock(
            create_group=mock.MagicMock(),
            join_group=mock.MagicMock(),
            heartbeat=mock.MagicMock(),
            watch_join_group=mock.MagicMock(),
            watch_leave_group=mock.MagicMock(),
            get_leader=mock.MagicMock(),
            stand_down_group_leader=mock.MagicMock(),
        )

        fake_get_coord = mock.patch.object(coordination, 'tz_coordination',
                                           autospec=True)
        self._fake_get_coord = fake_get_coord.start()
        self._fake_get_coord.get_coordinator = self.get_fake_coordinator

        self.addCleanup(mock.patch.stopall)
        self.queue = Queue()

    @mock.patch('akanda.rug.coordination.RugCoordinator.start')
    def test_setup(self, fake_start):
        self.coordinator = coordination.RugCoordinator(self.queue)
        self.assertEqual('memcache://foo_cache', self.coordinator.url)
        self.assertEqual('foo_coord_group', self.coordinator.group)
        self.assertEqual(9, self.coordinator.heartbeat_interval)
        self.assertEqual('foo_host', self.coordinator.host)
        self.assertTrue(fake_start.called)

    @mock.patch('akanda.rug.coordination.RugCoordinator.cluster_changed')
    def test_start(self, fake_cluster_changed):
        self.coordinator = coordination.RugCoordinator(self.queue)
        self.assertTrue(self.fake_coord.start.called)
        self.fake_coord.create_group.assert_called_with('foo_coord_group')
        self.fake_coord.join_group.assert_called_with('foo_coord_group')
        self.fake_coord.watch_join_group.assert_called_with(
            'foo_coord_group',
            fake_cluster_changed)
        self.fake_coord.watch_leave_group.assert_called_with(
            'foo_coord_group',
            fake_cluster_changed)
        self.assertTrue(self.fake_coord.heartbeat.called)
        fake_cluster_changed.assert_called_with(event=None, node_bootstrap=True)

    def test_start_raises(self):
        self.coordinator = coordination.RugCoordinator(self.queue)
        self.fake_coord.create_group.side_effect = (
            tz_coordination.GroupAlreadyExist(self.coordinator.group))
        self.fake_coord.join_group.side_effect = (
            tz_coordination.MemberAlreadyExist(
                self.coordinator.host, self.coordinator.group))
        return self.test_start()

    @mock.patch('time.sleep')
    @mock.patch('akanda.rug.coordination.RugCoordinator.stop')
    def test_run(self, fake_stop, fake_sleep):
        fake_sleep.side_effect = coordination.CoordinatorDone()
        self.coordinator = coordination.RugCoordinator(self.queue)
        self.coordinator.run()
        self.assertTrue(self.fake_coord.heartbeat.called)
        self.assertTrue(self.fake_coord.run_watchers.called)

    @mock.patch('akanda.rug.coordination.RugCoordinator.is_leader')
    def test_stop_not_leader(self, fake_is_leader):
        fake_is_leader.__get__ = mock.Mock(return_value=False)
        self.coordinator = coordination.RugCoordinator(self.queue)
        self.assertRaises(coordination.CoordinatorDone, self.coordinator.stop)
        self.fake_coord.leave_group.assert_called_with(self.coordinator.group)
        self.assertFalse(self.fake_coord.stand_down_group_leader.called)

    @mock.patch('akanda.rug.coordination.RugCoordinator.is_leader')
    def test_stop_leader(self, fake_is_leader):
        fake_is_leader.__get__ = mock.Mock(return_value=True)
        self.coordinator = coordination.RugCoordinator(self.queue)
        self.assertRaises(coordination.CoordinatorDone, self.coordinator.stop)
        self.fake_coord.stand_down_group_leader.assert_called_with(
            self.coordinator.group)
        self.fake_coord.leave_group.assert_called_with(self.coordinator.group)

    def test_members(self):
        fake_async_resp = mock.MagicMock(
            get=mock.MagicMock(return_value=['foo', 'bar'])
        )
        self.fake_coord.get_members.return_value = fake_async_resp
        self.coordinator = coordination.RugCoordinator(self.queue)
        self.assertEqual(self.coordinator.members, ['foo', 'bar'])
        self.fake_coord.get_members.assert_called_with(self.coordinator.group)

    def test_is_leader(self):
        fake_async_resp = mock.MagicMock(
            get=mock.MagicMock(return_value='foo_host')
        )
        self.fake_coord.get_leader.return_value = fake_async_resp
        self.coordinator = coordination.RugCoordinator(self.queue)
        self.assertEqual(self.coordinator.is_leader, True)
        self.fake_coord.get_leader.assert_called_with(self.coordinator.group)

    @mock.patch('akanda.rug.coordination.RugCoordinator.start')
    @mock.patch('akanda.rug.coordination.RugCoordinator.members')
    def test_cluster_changed(self, fake_members, fake_start):
        fake_members.__get__ = mock.Mock(return_value=['foo', 'bar'])
        self.coordinator = coordination.RugCoordinator(self.queue)
        expected_rebalance_event = event.Event(
            resource=event.Resource('*', '*', '*'),
            crud=event.REBALANCE,
            body={'members': ['foo', 'bar']})

        self.coordinator.cluster_changed(event=None)
        expected = ('*', expected_rebalance_event)
        res = self.queue.get()
        self.assertEqual(res, expected)
