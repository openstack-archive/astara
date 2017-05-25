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

from six.moves import range
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from astara import drivers
from astara.api import neutron
from astara.api import nova

LOG = logging.getLogger(__name__)

# Unused instances are launched with a known name
INSTANCE_FREE = 'ASTARA:UNUSED:%(resource_name)s'

# When an instance is reserved, its renamed accordingly
# TODO(adam_g): We ideally want to make all instance naming template-able
IN_USE_TEMPLATE = 'ak-%(resource_name)s-%(resource_id)s'


# Nova states
ACTIVE = 'active'
ERROR = 'error'
DELETING = 'deleting'

PEZ_LOCK = 'astara-pez'


class PezPoolExhausted(Exception):
    pass


class WorkerContext(object):
    """Holds resources owned by the worker and used by the Automaton.
    """

    def __init__(self):
        self.nova_client = nova.Nova(cfg.CONF)
        self.neutron_client = neutron.Neutron(cfg.CONF)


class PezPoolManager(object):
    """Astara Pez Pool Manager

    This manages a pool of instances of a configurable size.  All instance
    state is managed and tracked in Nova itself.

    Each iteratino of the manager's main loop will scan the service tenant's
    booted instances.  Instances named INSTANCE_FREE (defined above) will be
    considered unused.  If any of these instances are in ERROR state or are
    out dated in some way (ie, its image is not the currently configured
    image), they will be deleted from the pool and the manager will replenish
    the deficit on its next tick.

    Instances may be reserved for use via the get_instance() method. This
    simply renames the instance according to the ID of the thing that it will
    host and returns it to the caller. At this point, Pez no longer cares about
    the instance and will refill its position in the pool on next its next
    tick.

    The calling service is responsible for managing the lifecycle of the
    returned instance.  This includes attaching required ports, ensuring
    deletion/cleanup, etc. The instance will not be returned to the pool when
    it is no longer in use.
    """
    def __init__(self, image_uuid, flavor, pool_size, mgt_net_id):
        """
        :param image_uuid: UUID of backing image for managed instances.
        :param flavor: nova flavor id to be used for managed instances.
        :param mgt_net_id: UUID of management network. Each instance in the
                           pool is initially booted with a single port on this
                           network
        :param pool_size: The size of the pool
        """
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
        self.load_driver_config()

    def load_driver_config(self):
        self.images = {}
        self.flavors = {}
        self.drivers = [d for d in drivers.enabled_drivers()]
        for driver in self.drivers:
            self.images[driver.RESOURCE_NAME] = getattr(
                cfg.CONF, driver.RESOURCE_NAME).image_uuid
            self.flavors[driver.RESOURCE_NAME] = getattr(
                cfg.CONF, driver.RESOURCE_NAME).instance_flavor

    @lockutils.synchronized(PEZ_LOCK)
    def delete_instance(self, instance_uuid):
        LOG.info('Deleting instance %s.', instance_uuid)
        self.ctxt.nova_client.client.servers.delete(instance_uuid)
        self._delete_counters[instance_uuid] = timeutils.utcnow()

    def _check_err_instances(self, pools):
        """Scans the pool and deletes any instances in error state"""
        for resource, pool in copy.copy(pools).items():
            err_instances = [i for i in pool if i.status == ERROR]
            for err_inst in err_instances:
                LOG.error(
                    'Instance %s is in %s state, deleting.',
                    i.id, ERROR)
                del_instance = self.delete_instance(err_inst.id)
                i = pool.index(err_inst)
                pools[resource][i] = del_instance

    def _check_del_instances(self, pools):
        """Scans the pool for deleted instances and checks deletion timers"""
        # XXX: What do we do with instances stuck in deleting?
        # For now, just return stuck instances to caller and we can figure
        # out what to do with them later.
        stuck_instances = []
        del_instances = []
        for resource, pool in pools.items():
            del_instances += [i for i in pool if i.status == DELETING]

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
                    LOG.error(
                        'Instance %s is stuck in %s for more than %s '
                        'seconds.', i.id, DELETING, self.delete_timeout)
                    stuck_instances.append(del_inst)
        return stuck_instances

    def _check_outdated_instances(self, pools):
        outdated_instances = []
        for resource, pool in pools.items():
            for server in pool:
                if server.image['id'] != str(self.images[resource]):
                    LOG.info(
                        'Deleting instance %s with outdated image, '
                        '%s != %s',
                        server.id, server.image['id'], self.image_uuid)
                    outdated_instances.append(server)
                elif server.flavor['id'] != str(self.flavors[resource]):
                    LOG.info(
                        'Deleting instance %s with outdated flavor, '
                        '%s != %s',
                        server.id, server.flavor['id'], self.flavor)
                    outdated_instances.append(server)

        if outdated_instances:
            [self.delete_instance(i.id) for i in outdated_instances]

    def load_pools(self):
        pools = {}
        [pools.update({d.RESOURCE_NAME: []}) for d in self.drivers]
        for server in self.ctxt.nova_client.client.servers.list():
            for d in self.drivers:
                instance_free = INSTANCE_FREE % {
                    'resource_name': d.RESOURCE_NAME
                }
                if server.name.startswith(instance_free):
                    pools[d.RESOURCE_NAME].append(server)
        return pools

    @property
    def unused_instances(self):
        """Determines the size and contents of the current instance pool

        We list all nova servers according to the naming template.

        Any instances in an error state are deleted and will be replenished on
        the next run of the main loop.

        We time instance deletion and any servers that appear to be stuck in a
        deleted state will be reported as such. TODO(adam_g): We should figure
        out what to do with stuck instances?

        Any instances that appear to be outdated (ie, the server's image or
        flavor does not match whats configured) will be deleted and replenished
        on the next tick of hte main loop.

        :returns: a dict keyed by driver name, each value a list of nova server
                  objects that represents the current resources pool.
        """
        pools = self.load_pools()
        self._check_err_instances(pools)
        self._check_del_instances(pools)
        self._check_outdated_instances(pools)
        return pools

    def launch_instances(self, count, driver):
        LOG.info(
            'Launching %s %s instances.', driver.RESOURCE_NAME, count)
        for i in range(0, count):
            # NOTE: Use a fake UUID so astara-neutron's name matching still
            # catches this port as an astara port. This can be avoided if
            # we use a mgt security group in the future.
            mgt_port = self.ctxt.neutron_client.create_management_port(
                '00000000-0000-0000-0000-000000000000')
            nics = [{
                'net-id': mgt_port.network_id,
                'v4-fixed-ip': '',
                'port-id': mgt_port.id}]

            instance_name = INSTANCE_FREE % {
                'resource_name': driver.RESOURCE_NAME
            }
            image = self.images[driver.RESOURCE_NAME]
            flavor = self.flavors[driver.RESOURCE_NAME]

            self.ctxt.nova_client.client.servers.create(
                name=instance_name,
                image=image,
                flavor=flavor,
                nics=nics,
                config_drive=True,
                userdata=nova.format_userdata(mgt_port),
            )

    @lockutils.synchronized(PEZ_LOCK)
    def get_instance(self, resource_type, name, management_port=None,
                     instance_ports=None):
        """Get an instance from the pool.

        This involves popping it out of the pool, updating its name and
        attaching
        any ports.

        :param resource_type: The str driver name of the resource
        :param name: The requested name of the instance
        :param managment_port: The management port dict that was created for
                               the instance by the RUG.
        :param instance_ports: A list of dicts of ports to be attached to
                               instance upon reservation.

        :returns: A tuple containing (novaclient server object for the
                  reserved server, a port object for the management port,
                  a list of port objects that were attached the server)
        """
        instance_ports = instance_ports or []

        try:
            server = self.unused_instances[resource_type][0]
        except IndexError:
            raise PezPoolExhausted()

        LOG.info('Renaming instance %s to %s', server.name, name)
        server = self.ctxt.nova_client.client.servers.update(
            server, name=name)

        for port in instance_ports:
            LOG.info('Attaching instance port %s to %s (%s)',
                     port['id'], server.name, server.id)
            self.ctxt.nova_client.client.servers.interface_attach(
                server=server, port_id=port['id'], net_id=None, fixed_ip=None)

        mgt_port, instance_ports = (
            self.ctxt.neutron_client.get_ports_for_instance(server.id)
        )

        return (
            self.ctxt.nova_client.client.servers.get(server.id),
            mgt_port,
            instance_ports,
        )

    def start(self):
        """The pool manager main loop.

        The bulk of the algorithm exists in the 'unused_instances' property.
        This main loop simply checks for a deficit in the pool and dispatches
        a 'launch_instances' call when a deficit needs to be filled.
        """
        while True:
            cur_pools = self.unused_instances
            report = []
            for driver in self.drivers:
                report.append(
                    '%s:%s/%s' %
                    (driver.RESOURCE_NAME,
                     len(cur_pools[driver.RESOURCE_NAME]),
                     self.pool_size))
            LOG.debug('Current pools: %s' % ' '.join(report))

            for driver in self.drivers:
                cur_pool = cur_pools[driver.RESOURCE_NAME]
                deficit = self.pool_size - len(cur_pool)
                if deficit:
                    LOG.info(
                        'Need to launch %s more %s instance(s).',
                        deficit, driver.RESOURCE_NAME)
                    self.launch_instances(
                        driver=driver, count=deficit)
            time.sleep(self.poll_interval)
