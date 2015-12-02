# Copyright 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2015 Akanda, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import hashlib

import mock
from oslo_config import cfg
from testtools import matchers

from astara.common import hash_ring
from astara.test.unit import base
# from astara.tests.unit.db import base as db_base

CONF = cfg.CONF


class HashRingTestCase(base.RugTestBase):

    # NOTE(deva): the mapping used in these tests is as follows:
    #             if hosts = [foo, bar]:
    #                fake -> foo, bar
    #             if hosts = [foo, bar, baz]:
    #                fake -> foo, bar, baz
    #                fake-again -> bar, baz, foo

    @mock.patch.object(hashlib, 'md5', autospec=True)
    def test__hash2int_returns_int(self, mock_md5):
        CONF.set_override('hash_partition_exponent', 0)
        r1 = 32 * 'a'
        r2 = 32 * 'b'
        mock_md5.return_value.hexdigest.side_effect = [r1, r2]

        hosts = ['foo', 'bar']
        replicas = 1
        ring = hash_ring.HashRing(hosts, replicas=replicas)

        self.assertIn(int(r1, 16), ring._host_hashes)
        self.assertIn(int(r2, 16), ring._host_hashes)

    def test_create_ring(self):
        hosts = ['foo', 'bar']
        replicas = 2
        ring = hash_ring.HashRing(hosts, replicas=replicas)
        self.assertEqual(set(hosts), ring.hosts)
        self.assertEqual(replicas, ring.replicas)

    def test_create_with_different_partition_counts(self):
        hosts = ['foo', 'bar']
        CONF.set_override('hash_partition_exponent', 2)
        ring = hash_ring.HashRing(hosts)
        self.assertEqual(2 ** 2 * 2, len(ring._partitions))

        CONF.set_override('hash_partition_exponent', 8)
        ring = hash_ring.HashRing(hosts)
        self.assertEqual(2 ** 8 * 2, len(ring._partitions))

        CONF.set_override('hash_partition_exponent', 16)
        ring = hash_ring.HashRing(hosts)
        self.assertEqual(2 ** 16 * 2, len(ring._partitions))

    def test_distribution_one_replica(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash_ring.HashRing(hosts, replicas=1)
        fake_1_hosts = ring.get_hosts('fake')
        fake_2_hosts = ring.get_hosts('fake-again')
        # We should have one hosts for each thing
        self.assertThat(fake_1_hosts, matchers.HasLength(1))
        self.assertThat(fake_2_hosts, matchers.HasLength(1))
        # And they must not be the same answers even on this simple data.
        self.assertNotEqual(fake_1_hosts, fake_2_hosts)

    def test_distribution_two_replicas(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash_ring.HashRing(hosts, replicas=2)
        fake_1_hosts = ring.get_hosts('fake')
        fake_2_hosts = ring.get_hosts('fake-again')
        # We should have two hosts for each thing
        self.assertThat(fake_1_hosts, matchers.HasLength(2))
        self.assertThat(fake_2_hosts, matchers.HasLength(2))
        # And they must not be the same answers even on this simple data
        # because if they were we'd be making the active replica a hot spot.
        self.assertNotEqual(fake_1_hosts, fake_2_hosts)

    def test_distribution_three_replicas(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash_ring.HashRing(hosts, replicas=3)
        fake_1_hosts = ring.get_hosts('fake')
        fake_2_hosts = ring.get_hosts('fake-again')
        # We should have two hosts for each thing
        self.assertThat(fake_1_hosts, matchers.HasLength(3))
        self.assertThat(fake_2_hosts, matchers.HasLength(3))
        # And they must not be the same answers even on this simple data
        # because if they were we'd be making the active replica a hot spot.
        self.assertNotEqual(fake_1_hosts, fake_2_hosts)
        self.assertNotEqual(fake_1_hosts[0], fake_2_hosts[0])

    def test_ignore_hosts(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash_ring.HashRing(hosts, replicas=1)
        equals_bar_or_baz = matchers.MatchesAny(
            matchers.Equals(['bar']),
            matchers.Equals(['baz']))
        self.assertThat(
            ring.get_hosts('fake', ignore_hosts=['foo']),
            equals_bar_or_baz)
        self.assertThat(
            ring.get_hosts('fake', ignore_hosts=['foo', 'bar']),
            equals_bar_or_baz)
        self.assertEqual([], ring.get_hosts('fake', ignore_hosts=hosts))

    def test_ignore_hosts_with_replicas(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash_ring.HashRing(hosts, replicas=2)
        self.assertEqual(
            set(['bar', 'baz']),
            set(ring.get_hosts('fake', ignore_hosts=['foo'])))
        self.assertEqual(
            set(['baz']),
            set(ring.get_hosts('fake', ignore_hosts=['foo', 'bar'])))
        self.assertEqual(
            set(['baz', 'foo']),
            set(ring.get_hosts('fake-again', ignore_hosts=['bar'])))
        self.assertEqual(
            set(['foo']),
            set(ring.get_hosts('fake-again', ignore_hosts=['bar', 'baz'])))
        self.assertEqual([], ring.get_hosts('fake', ignore_hosts=hosts))

    def _compare_rings(self, nodes, conductors, ring,
                       new_conductors, new_ring):
        delta = {}
        mapping = dict((node, ring.get_hosts(node)[0]) for node in nodes)
        new_mapping = dict(
            (node, new_ring.get_hosts(node)[0]) for node in nodes)

        for key, old in mapping.items():
            new = new_mapping.get(key, None)
            if new != old:
                delta[key] = (old, new)
        return delta

    def test_rebalance_stability_join(self):
        num_conductors = 10
        num_nodes = 10000
        # Adding 1 conductor to a set of N should move 1/(N+1) of all nodes
        # Eg, for a cluster of 10 nodes, adding one should move 1/11, or 9%
        # We allow for 1/N to allow for rounding in tests.
        redistribution_factor = 1.0 / num_conductors

        nodes = [str(x) for x in range(num_nodes)]
        conductors = [str(x) for x in range(num_conductors)]
        new_conductors = conductors + ['new']
        delta = self._compare_rings(
            nodes, conductors, hash_ring.HashRing(conductors),
            new_conductors, hash_ring.HashRing(new_conductors))

        self.assertTrue(len(delta) < num_nodes * redistribution_factor)

    def test_rebalance_stability_leave(self):
        num_conductors = 10
        num_nodes = 10000
        # Removing 1 conductor from a set of N should move 1/(N) of all nodes
        # Eg, for a cluster of 10 nodes, removing one should move 1/10, or 10%
        # We allow for 1/(N-1) to allow for rounding in tests.
        redistribution_factor = 1.0 / (num_conductors - 1)

        nodes = [str(x) for x in range(num_nodes)]
        conductors = [str(x) for x in range(num_conductors)]
        new_conductors = conductors[:]
        new_conductors.pop()
        delta = self._compare_rings(
            nodes, conductors, hash_ring.HashRing(conductors),
            new_conductors, hash_ring.HashRing(new_conductors))

        self.assertTrue(len(delta) < num_nodes * redistribution_factor)

    def test_more_replicas_than_hosts(self):
        hosts = ['foo', 'bar']
        ring = hash_ring.HashRing(hosts, replicas=10)
        self.assertEqual(set(hosts), set(ring.get_hosts('fake')))

    def test_ignore_non_existent_host(self):
        hosts = ['foo', 'bar']
        ring = hash_ring.HashRing(hosts, replicas=1)
        self.assertEqual(['foo'], ring.get_hosts('fake',
                                                 ignore_hosts=['baz']))

    def test_create_ring_invalid_data(self):
        hosts = None
        self.assertRaises(hash_ring.Invalid,
                          hash_ring.HashRing,
                          hosts)

    def test_get_hosts_invalid_data(self):
        hosts = ['foo', 'bar']
        ring = hash_ring.HashRing(hosts)
        self.assertRaises(hash_ring.Invalid,
                          ring.get_hosts,
                          None)


class HashRingManagerTestCase(base.RugTestBase):

    def setUp(self):
        super(HashRingManagerTestCase, self).setUp()
        self.ring_manager = hash_ring.HashRingManager()

    def test_reset(self):
        self.ring_manager.rebalance(hosts=['foo', 'bar'])
        self.ring_manager.reset()
        self.assertIsNone(self.ring_manager._hash_ring)

    def test_rebalance(self):
        self.ring_manager.rebalance(hosts=['foo', 'bar'])
        self.assertEqual(set(['foo', 'bar']), self.ring_manager.hosts)
        self.ring_manager.rebalance(hosts=['bar', 'baz'])
        self.assertEqual(set(['bar', 'baz']), self.ring_manager.hosts)
