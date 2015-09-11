# Copyright 2015 Akanda, Inc
#
# Author: Akanda, Inc
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

import copy
import time

from akanda.rug.common.i18n import _LE, _LI
from akanda.rug.api import nova
from akanda.rug.api import neutron

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

LOG = logging.getLogger(__name__)


# Unused instances are launched with a known name
INSTANCE_FREE = 'ak-unused'

# When an instance is reserved, its renamed accordingly
# XXX: Extend name to reflect resource type? ie, ak-router-$uuid
IN_USE_TEMPLATE = 'ak-%(resource_id)s'


# Nova states
ACTIVE = 'active'
ERROR = 'error'
DELETING = 'deleting'

PEZ_LOCK = 'akanda-pez'


class PezPoolExhausted(Exception):
    pass


# XXX Re-use worker context from elsewhere
class WorkerContext(object):
    """Holds resources owned by the worker and used by the Automaton.
    """

    def __init__(self):
        self.nova_client = nova.Nova(cfg.CONF)
        self.neutron_client = neutron.Neutron(cfg.CONF)

class PezPoolManager(object):
    def __init__(self, image_uuid, flavor, pool_size, mgt_net_id):
        self.image_uuid = image_uuid
        self.flavor = flavor
        self.mgt_net_id = mgt_net_id
        self.pool_size = int(pool_size)
        self.poll_interval = 3
        self.ctxt = WorkerContext()
        self.boot_timeout = 120
        self.delete_timeout = 30

        # used to track boot/delete timeouts
        self._delete_counters = {}
        self._boot_counters = {}

    @lockutils.synchronized(PEZ_LOCK)
    def delete_instance(self, instance_uuid):
        # XXX todo
        LOG.info(_LI('Deleting instance %s.'), instance_uuid)
        self.ctxt.nova_client.servers.delete(instance_uuid)
        self._delete_counters[i.id] = timeutils.utcnow()

    def _check_err_instances(self, pool):
        """Scans the pool and deletes any instances in error state"""
        err_instances = [i for i in pool if i.status == ERROR]
        for err_inst in err_instances:
            LOG.error(_LE('Instance %s is in %s state, deleting.'), i.id, ERROR)
            del_instance = self.delete_instance(err_inst.id)
            i = pool.index(err_inst)
            pool[i] = del_instance

    def _check_del_instances(self, pool):
        """Scans the pool for deleted instances and checks deletion timers"""
        # XXX: What do we do with instances stuck in deleting?
        #   - Leave them hanging around and replace them with new ones?
        #   - Count them against pool quota?
        # For now, just return stuck instances to caller and we can figure
        # out what to do with them later.
        stuck_instances = []
        del_instances = [i for i in pool if i.status == DELETING]

        # clean out counters for old instances that have been deleted entirely
        if self._delete_counters:
            del_instance_ids = [i.id for i in del_instances]
            for inst_id in copy.copy(self._delete_counters):
                if inst_id not in del_instance_ids:
                    self._delete_counters.pop(inst_id)
        for del_inst in del_instances:
            if del_inst.id not in self._delete_counters:
                self._delete_counters[del_inst.id] = timeutils.utcnow()
            else:
                if timeutils.is_older_than(self._delete_counters[del_inst.id],
                                           self.delete_timeout):
                    LOG.error(_LE(
                        'Instance %s is stuck in %s for more than %s '
                        'seconds.'), i.id, DELETING, self.delete_timeout)
                    stuck_instances.append(del_inst)
        return stuck_instances

    @property
    def unused_instances(self):
        pool = [s for s in self.ctxt.nova_client.client.servers.list()
                if s.name.startswith(INSTANCE_FREE)]
        self._check_err_instances(pool)
        self._check_del_instances(pool)
        return pool

    def launch_instances(self, count):
        LOG.info(_LI('Launching %s instances.'), count)
        for i in range(0, count):
            # XXX we should probably rename the port as well as instance
            # when we reserve it
            mgt_port = self.ctxt.neutron_client.create_management_port(
                'UNUSED')
            nics = [{
                'net-id': mgt_port.network_id,
                'v4-fixed-ip': '',
                'port-id': mgt_port.id}]

            userdata = nova.format_userdata(mgt_port)
            res = self.ctxt.nova_client.client.servers.create(
                name=INSTANCE_FREE,
                image=self.image_uuid,
                flavor=self.flavor,
                nics=nics,
                config_drive=True,
                userdata=nova.format_userdata(mgt_port),
            )

    @lockutils.synchronized(PEZ_LOCK)
    def get_instance(self, resource_id, management_port=None,
                     instance_ports=None):
        """Get an instance from the pool.

        This involves popping it out of the pool, updating its name and
        attaching
        any ports.

        :param resoruce_id: The uuid of the resource it will be used
                            for (ie, router id)

        :returns: A novaclient server object for the reserved server.
        """
        instance_ports = instance_ports or []

        try:
            server = self.unused_instances[0]
        except IndexError:
            raise PezPoolExhausted()

        port = instance_ports[0]
        client = self.ctxt.nova_client.client

        name = IN_USE_TEMPLATE % locals()
        LOG.info(_LI('Renaming instance %s to %s'), server.name, name)
        server = self.ctxt.nova_client.client.servers.update(
            server, name=name)

        for port in instance_ports:
            LOG.info(_LI('Attaching instance port %s to %s (%s)'),
                     port['id'], server.name, server.id)
            self.ctxt.nova_client.client.servers.interface_attach(
                server=server, port_id=port['id'], net_id=None, fixed_ip=None)

        return self.ctxt.nova_client.client.servers.get(server.id)

    def start(self):
        """The pool manager main loop:
        - cur_pool_size = list all instances named INSTANCE_FREE
        - cur_pool_size = cur_pool_size - (DELETED, ERROR) -> GC
        - update boot timeouts
        - cur_pool_size = cur_pool_size - (timed out instances) -> GC
        - deficit = pool_size - cur_pool_size
        - launch instances for deficit
        """
        del_counter = {}
        boot_counter = {}

        while True:
            cur_pool = self.unused_instances
            LOG.info(_LI('Pool size: %s/%s'), len(cur_pool), self.pool_size)

            deficit = self.pool_size - len(cur_pool)

            if deficit:
                LOG.info(_LI('Need to launch %s more instance(s).'), deficit)
                self.launch_instances(count=deficit)

            time.sleep(self.poll_interval)
