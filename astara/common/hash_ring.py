# Copyright 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2015 Akanda, Inc.
#
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

import bisect
import hashlib
import threading

from oslo_config import cfg
import six
from six.moves import range

from astara.common.i18n import _

hash_opts = [
    cfg.IntOpt('hash_partition_exponent',
               default=5,
               help='Exponent to determine number of hash partitions to use '
                    'when distributing load across Rugs. Larger values '
                    'will result in more even distribution of load and less '
                    'load when rebalancing the ring, but more memory usage. '
                    'Number of partitions per rug is '
                    '(2^hash_partition_exponent). This determines the '
                    'granularity of rebalancing: given 10 hosts, and an '
                    'exponent of the 2, there are 40 partitions in the ring.'
                    'A few thousand partitions should make rebalancing '
                    'smooth in most cases. The default is suitable for up to '
                    'a few hundred rugs. Too many partitions has a CPU '
                    'impact.'),
]

CONF = cfg.CONF
CONF.register_opts(hash_opts)


# A static key that can be used to choose a  single host when from the
# ring we have no other data to hash with.
DC_KEY = 'astara_designated_coordinator'


class Invalid(Exception):
    pass


# Lifted from ironic with some modifications.
class HashRing(object):
    """A stable hash ring.

    We map item N to a host Y based on the closest lower hash:

    - hash(item) -> partition
    - hash(host) -> divider
    - closest lower divider is the host to use
    - we hash each host many times to spread load more finely
      as otherwise adding a host gets (on average) 50% of the load of
      just one other host assigned to it.
    """

    def __init__(self, hosts, replicas=1):
        """Create a new hash ring across the specified hosts.

        :param hosts: an iterable of hosts which will be mapped.
        :param replicas: number of hosts to map to each hash partition,
                         or len(hosts), which ever is lesser.
                         Default: 1

        """
        try:
            self.hosts = set(hosts)
            self.replicas = replicas if replicas <= len(hosts) else len(hosts)
        except TypeError:
            raise Invalid(
                _("Invalid hosts supplied when building HashRing."))

        self._host_hashes = {}
        for host in hosts:
            key = str(host).encode('utf8')
            key_hash = hashlib.md5(key)
            for p in range(2 ** CONF.hash_partition_exponent):
                key_hash.update(key)
                hashed_key = self._hash2int(key_hash)
                self._host_hashes[hashed_key] = host
        # Gather the (possibly colliding) resulting hashes into a bisectable
        # list.
        self._partitions = sorted(self._host_hashes.keys())

    def _hash2int(self, key_hash):
        """Convert the given hash's digest to a numerical value for the ring.

        :returns: An integer equivalent value of the digest.
        """
        return int(key_hash.hexdigest(), 16)

    def _get_partition(self, data):
        try:
            if six.PY3 and data is not None:
                data = data.encode('utf-8')
            key_hash = hashlib.md5(data)
            hashed_key = self._hash2int(key_hash)
            position = bisect.bisect(self._partitions, hashed_key)
            return position if position < len(self._partitions) else 0
        except TypeError:
            raise Invalid(
                _("Invalid data supplied to HashRing.get_hosts."))

    def get_hosts(self, data, ignore_hosts=None):
        """Get the list of hosts which the supplied data maps onto.

        :param data: A string identifier to be mapped across the ring.
        :param ignore_hosts: A list of hosts to skip when performing the hash.
                             Useful to temporarily skip down hosts without
                             performing a full rebalance.
                             Default: None.
        :returns: a list of hosts.
                  The length of this list depends on the number of replicas
                  this `HashRing` was created with. It may be less than this
                  if ignore_hosts is not None.
        """
        hosts = []
        if ignore_hosts is None:
            ignore_hosts = set()
        else:
            ignore_hosts = set(ignore_hosts)
            ignore_hosts.intersection_update(self.hosts)
        partition = self._get_partition(data)
        for replica in range(0, self.replicas):
            if len(hosts) + len(ignore_hosts) == len(self.hosts):
                # prevent infinite loop - cannot allocate more fallbacks.
                break
            # Linear probing: partition N, then N+1 etc.
            host = self._get_host(partition)
            while host in hosts or host in ignore_hosts:
                partition += 1
                if partition >= len(self._partitions):
                    partition = 0
                host = self._get_host(partition)
            hosts.append(host)
        return hosts

    def _get_host(self, partition):
        """Find what host is serving a partition.

        :param partition: The index of the partition in the partition map.
            e.g. 0 is the first partition, 1 is the second.
        :return: The host object the ring was constructed with.
        """
        return self._host_hashes[self._partitions[partition]]


class HashRingManager(object):
    _hash_ring = None
    _lock = threading.Lock()

    def __init__(self):
        self._hosts = []

    @property
    def ring(self):
        # Hot path, no lock
        if self._hash_ring is not None:
            return self._hash_ring

        with self._lock:
            if self._hash_ring is None:
                ring = self._load_hash_ring()
                self.__class__._hash_ring = ring
            return self._hash_ring

    @property
    def hosts(self):
        return self.ring.hosts

    def _load_hash_ring(self):
        return HashRing(self._hosts)

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._hash_ring = None

    def rebalance(self, hosts):
        self.reset()
        with self._lock:
            self._hosts = hosts
