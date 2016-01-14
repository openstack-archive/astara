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

from datetime import datetime
from functools import wraps
import time
import six

from oslo_config import cfg

from astara.drivers import states
from astara.common.i18n import _LE, _LI
from astara.common import container


CONF = cfg.CONF
INSTANCE_MANAGER_OPTS = [
    cfg.IntOpt(
        'hotplug_timeout',
        default=10,
        help='The amount of time to wait for nova to hotplug/unplug '
        'networks from the instances.'),
    cfg.IntOpt(
        'boot_timeout', default=600),
    cfg.IntOpt(
        'error_state_cooldown',
        default=30,
        help='Number of seconds to ignore new events when an instance goes '
        'into ERROR state.',
    ),
]
CONF.register_opts(INSTANCE_MANAGER_OPTS)


def _generate_interface_map(instance, interfaces):
    # TODO(mark): We're in the first phase of VRRP, so we need
    # map the interface to the network ID.
    # Eventually we'll send VRRP data and real interface data
    port_mac_to_net = {
        p.mac_address: p.network_id
        for p in instance.ports
    }
    # Add in the management port
    mgt_port = instance.management_port
    port_mac_to_net[mgt_port.mac_address] = mgt_port.network_id
    # this is a network to logical interface id
    return {
        port_mac_to_net[i['lladdr']]: i['ifname']
        for i in interfaces if i['lladdr'] in port_mac_to_net
    }


def synchronize_driver_state(f):
    """Wrapper that triggers a driver's synchronize_state function"""
    def wrapper(self, *args, **kw):
        state = f(self, *args, **kw)
        self.resource.synchronize_state(*args, state=state)
        return state
    return wrapper


def ensure_cache(f):
    """Decorator to wrap around any function that uses self.instance_info.

    Ensures that self.instance_info is up to date and catches instances in a
    GONE or missing state before wasting cycles trying to do something with it.

    NOTE: This replaces the old function called _ensure_cache made a Decorator
    rather than calling it explicitly at the start of all those functions.
    """
    @wraps(f)
    def wrapper(self, worker_context, *args, **kw):
        # insure that self.instance_info is current before doing anything.
        instances = worker_context.nova_client.get_instances_for_obj(
            self.resource.name)
        for inst_info in instances:
            self.instances[inst_info.id_] = inst_info

        self.instances.update_ports(worker_context)

        return f(self, worker_context, *args, **kw)

    return wrapper


class BootAttemptCounter(object):
    def __init__(self):
        self._attempts = 0

    def start(self):
        self._attempts += 1

    def reset(self):
        self._attempts = 0

    @property
    def count(self):
        return self._attempts


class InstanceGroupManager(container.ResourceContainer):
    def __init__(self, log, resource):
        super(InstanceGroupManager, self).__init__()
        self.log = log
        self.resource = resource
        self._alive = set()

    def validate_ports(self):
        """Checks whether instance have management ports attached

        :returns: tuple containing two lists:
             (instances that have ports, instances that don't)
        """
        has_ports = set()
        for inst_info in set(self.resources.values()):
            if inst_info.management_address:
                has_ports.add(inst_info)
        return has_ports, set(self.resources.values()) - has_ports

    def are_alive(self):
        """Calls the check_check function all instances to ensure liveliness

        :returns: tuple containing two lists (alive_instances, dead_instances)
        """
        alive = set()
        for i in six.moves.range(cfg.CONF.max_retries):
            for inst_info in set(self.resources.values()) - alive:
                if (inst_info.management_address and
                   self.resource.is_alive(inst_info.management_address)):
                    self.log.debug(
                        'Instance %s found alive after %s of %s attempts',
                        inst_info.id_, i, cfg.CONF.max_retries)
                    alive.add(inst_info)
                else:
                    self.log.debug(
                        'Alive check failed for instance %s. Attempt %d of %d',
                        inst_info.id_, i, cfg.CONF.max_retries)

            if not alive - set(self.resources.values()):
                self._alive = [i.id_ for i in alive]
                return alive, []

        if not alive:
            self.log.debug(
                'Alive check failed for all instnaces after %s attempts.',
                cfg.CONF.max_retries)
            return [], self.resources.values()
        dead = set(self.resources.values()) - alive
        self._alive = [i.id_ for i in alive - dead]
        return list(alive), list(dead)

    def update_ports(self, worker_context):
        for instance_info in self.resources.values():
            if not instance_info:
                continue
            (
                instance_info.management_port,
                instance_info.ports
            ) = worker_context.neutron.get_ports_for_instance(
                instance_info.id_
            )

    def get_interfaces(self):
        interfaces = {}
        for inst in self.resources.values():
            if inst.id_ not in self._alive:
                self.log.debug("SKIPING %s ITS NOT ALIVE YET", inst)
                continue
            else:
                interfaces[inst] = self.resource.get_interfaces(
                    inst.management_address)
        return interfaces

    def verify_interfaces(self, ports):
        """Verify at least one instance in group has correct ports plugged"""
        for inst, interfaces in self.get_interfaces().items():
            actual_macs = set((iface['lladdr'] for iface in interfaces))
            self.log.debug(
                'MACs found on %s: %s', inst.id_,
                ', '.join(sorted(actual_macs)))
            if not all(
                getattr(p, 'mac_address', None) for p in ports
            ):
                return False

            num_instance_ports = len(list(inst.ports))
            num_logical_ports = len(list(ports))
            if num_logical_ports != num_instance_ports:
                self.log.debug(
                    'Expected %s instance ports but found %s',
                    num_logical_ports, num_instance_ports)
                return False

            expected_macs = set(p.mac_address
                                for p in inst.ports)
            expected_macs.add(inst.management_port.mac_address)
            self.log.debug(
                'MACs expected on: %s, %s',
                inst.id_, ', '.join(sorted(expected_macs)))

            if actual_macs == expected_macs:
                self.log.debug('Found all expected MACs on %s', inst.id_)
                return True

        self.log.debug(
            'Did not find all expected MACs on %s, actual MACs: %s',
            self.resource.id, ', '.join(actual_macs))
        return False

    def _update_config(self, instance, config):
        self.log.debug(
            'Updating config for instance %s on resource %s',
            instance.id_, self.resource.id)
        self.log.debug('New config: %r', config)
        attempts = cfg.CONF.max_retries
        for i in six.moves.range(attempts):
            try:
                self.resource.update_config(
                    instance.management_address,
                    config)
            except Exception:
                if i == attempts - 1:
                    # Only log the traceback if we encounter it many times.
                    self.log.exception(_LE('failed to update config'))
                else:
                    self.log.debug(
                        'failed to update config, attempt %d',
                        i
                    )
                time.sleep(cfg.CONF.retry_delay)
            else:
                self.log.info('Instance config updated')
                return True
        else:
            return False

    def _ha_config(self, instance):
        """Builds configuration describing the HA cluster

        This informs the instance about any configuration relating to the HA
        cluster it should be joining.  ATM this is primarily used to inform
        an instance about the management addresses of its peers.

        :param instance: InstanceInfo object
        :returns: dict of HA configuration
        """
        peers = [
            i.management_address for i in self.resources.values()
            if i.management_address != instance.management_address]

        # determine cluster priority by instance age. the older instance
        # gets the higher priority
        sorted_by_age = sorted(
            self.resources.values(), key=lambda i: i.time_since_boot,
            reverse=True)
        if sorted_by_age.index(instance) == 0:
            priority = 100
        else:
            priority = 50

        return {
            'peers': peers,
            'priority': priority,
        }

    def configure(self, worker_context):
        # XXX config update can be dispatched to threads to speed
        # things up across multiple instances
        failed = []

        # get_interfaces() return returns only instances that are up and ready
        # for config
        instances_interfaces = self.get_interfaces()

        for inst, interfaces in instances_interfaces.items():
            # sending all the standard config over to the driver for
            # final updates
            config = self.resource.build_config(
                worker_context,
                inst.management_port,
                _generate_interface_map(inst, interfaces)
            )

            # while drivers are free to express their own ha config
            # requirements, the instance manager is the only one with
            # high level view of the cluster, ie knowledge of membership
            if self.resource.is_ha:
                config['ha_config'] = config.get('ha') or {}
                config['ha_config'].update(self._ha_config(inst))

            self.log.debug(
                'preparing to update config for instance %s on %s resource '
                'to %r', inst.id_, self.resource.RESOURCE_NAME, config)

            if not self._update_config(inst, config):
                failed.append(inst)

        if set(failed) == set(self.resources.values()):
            self.log.error(
                'Could not update config for any instances on %s resource %s, '
                'marking resource state %s',
                self.resource.id, self.resource.RESOURCE_NAME, states.RESTART)
            return states.RESTART
        elif failed:
            self.log.error(
                'Could not update config for some instances on %s '
                'resource %s marking %s resource state',
                self.resource.id, self.resource.RESOURCE_NAME, states.RESTART)

            return states.DEGRADED
        else:
            updated_instances = len(instances_interfaces.keys())
            total_instances = len(self.resources.values())

            # we've only managed to update a subset of the nodes, perhaps
            # because we're rebuilding a degraded cluster and one node is still
            # booting. kick back to degraded start from CreateInstance again.
            if updated_instances != total_instances:
                self.log.debug('Config updated on %s of %s instances')
                return states.DEGRADED

            self.log.debug(
                'Config updated across all instances on %s resource %s',
                self.resource.RESOURCE_NAME, self.resource.id)
            return states.CONFIGURED

    def delete(self, instance, destroy=False):
        del self.resources[instance]

    def refresh(self, worker_context):
        for i in self.resources.values():
            if not worker_context.nova_client.update_instance_info(i):
                del self.resources[i.id_]

    def destroy(self, worker_context):
        worker_context.nova_client.delete_instances_and_wait(
            self.resources.values())

    def remove(self, worker_context, instance):
        worker_context.nova_client.destroy_instance(instance)
        del self.resources[instance.id_]

    @property
    def next_instance_index(self):
        ids = [
            int(i.name.split('_')[1]) for i in
            self.resources.values()]
        try:
            return max(ids) + 1
        except ValueError:
            return 0

    def create(self, worker_context, resource):
        # TODO: derive from resource based on HA needs
        instance_count = 2

        to_boot = instance_count - len(self.resources.items())
        self.log.debug(
            'Booting an additional %s instance(s) for resource %s',
            to_boot, resource.id)

        for i in six.moves.range(to_boot):
            name = '%s_%s' % (resource.name, self.next_instance_index)
            instance = worker_context.nova_client.boot_instance(
                resource_type=self.resource.RESOURCE_NAME,
                prev_instance_info=None,
                name=name,
                image_uuid=self.resource.image_uuid,
                flavor=self.resource.flavor,
                make_ports_callback=self.resource.make_ports(worker_context)

            )
            self.resources[instance.id_] = instance

    @property
    def required_instance_count(self):
        if self.resource.is_ha:
            return 2
        else:
            return 1

    @property
    def instance_count(self):
        return len(self.resources.values())

    @property
    def cluster_degraded(self):
        if self.instance_count < self.required_instance_count:
            return True
        for inst in self.resources.values():
            if inst.booting:
                return True


class InstanceManager(object):

    def __init__(self, resource, worker_context):
        """The instance manager is your interface to the running instance.
        wether it be virtual, container or physical.

        Service specific code lives in the driver which is passed in here.

        :param resource: An driver instance for the managed resource
        :param resource_id: UUID of logical resource
        :param worker_context:
        """
        self.resource = resource
        self.log = self.resource.log

        self.state = states.DOWN

        self.instance_info = None
        self.instances = InstanceGroupManager(self.log, self.resource)
        self.last_error = None
        self._boot_counter = BootAttemptCounter()
        self._boot_logged = []
        self._last_synced_status = None

        self.state = self.update_state(worker_context, silent=True)

    @property
    def attempts(self):
        """Property which returns the boot count.

        :returns Int:
        """
        return self._boot_counter.count

    def reset_boot_counter(self):
        """Resets the boot counter.

        :returns None:
        """
        self._boot_counter.reset()

    @synchronize_driver_state
    @ensure_cache
    def update_state(self, worker_context, silent=False):
        """Updates state of the instance and, by extension, its logical resource

        :param worker_context:
        :param silent:
        :returns: state
        """
        if self.resource.get_state(worker_context) == states.GONE:
            self.log.debug('%s driver reported its state is %s',
                           self.resource.RESOURCE_NAME, states.GONE)
            self.state = states.GONE
            return self.state

        if not self.instances:
            self.log.info(_LI('no backing instance(s), marking as %s'),
                          states.DOWN)
            self.state = states.DOWN
            return self.state
        elif self.instances.cluster_degraded is True:
            self.log.info(_LI(
                'instance cluster for resource %s reports degraded'),
                self.resource.id)
            self.state = states.DEGRADED
            return self.state

        has_ports, no_ports = self.instances.validate_ports()

        # ports_state=None means no instances have ports
        if not has_ports:
            self.log.debug('waiting for instance ports to be attached')
            self.state = states.BOOTING
            return self.state

        # XXX TODO need to account for when only a subset of the cluster have
        # correct ports, kick back to Replug

        alive, dead = self.instances.are_alive()
        if not alive:
            # alive checked failed on all instances for an already configured
            # resource, mark it down.
            # XXX need to track timeouts per instance
            # self._check_boot_timeout()

            if self.state == states.CONFIGURED:
                self.log.debug('No instance(s) alive, marking it as %s',
                               states.DOWN)
                self.state = states.DOWN
                return self.state
        elif dead:
            # some subset of instances reported not alive, mark it degraded.
            if self.state == states.CONFIGURED:
                for i in dead:
                    instance = worker_context.nova_client.get_instance_by_id(
                        i.id_)
                    if instance is None and self.state != states.ERROR:
                        self.log.info(
                            'Instance %s was found; rebooting', i.id_)
                    self.instances.delete(i)
            self.state = states.DEGRADED
            return self.state

        self.instances.refresh(worker_context)
        if self.state == states.CONFIGURED:
            for i in alive:
                if not i.booting and i not in self._boot_logged:
                    self.log.info(
                        '%s booted in %s seconds after %s attempts',
                        self.resource.RESOURCE_NAME,
                        i.time_since_boot.total_seconds(),
                        self._boot_counter.count)
                    self._boot_logged.append(i)
        else:
            if alive:
                self.state = states.UP

        return self.state

    @ensure_cache
    def boot(self, worker_context):
        """Boots the instance with driver pre/post boot hooks.

        :returns: None
        """
        self.log.info('Booting %s' % self.resource.RESOURCE_NAME)
        self.state = states.DOWN
        self._boot_counter.start()

        # driver preboot hook
        self.resource.pre_boot(worker_context)

        try:
            self.instances.create(worker_context, self.resource)
            if not self.instances:
                self.log.info(_LI('Previous instances are still deleting'))
                # Reset the boot counter, causing the state machine to start
                # again with a new Instance.
                self.reset_boot_counter()
                return
        except:
            self.log.exception(_LE('Instances failed to start boot'))
        else:
            self.state = states.BOOTING

        # driver post boot hook
        self.resource.post_boot(worker_context)

    @synchronize_driver_state
    @ensure_cache
    def set_error(self, worker_context, silent=False):
        """Set the internal and neutron status for the router to states.ERROR.

        This is called from outside when something notices the router
        is "broken". We don't use it internally because this class is
        supposed to do what it's told and not make decisions about
        whether or not the router is fatally broken.
        """
        self.state = states.ERROR
        self.last_error = datetime.utcnow()
        return self.state

    @synchronize_driver_state
    @ensure_cache
    def clear_error(self, worker_context, silent=False):
        """Clear the internal error state.

        This is called from outside when something wants to force a
        router rebuild, so that the state machine that checks our
        status won't think we are broken unless we actually break
        again.
        """
        # Clear the boot counter.
        self._boot_counter.reset()
        self.state = states.DOWN
        return self.state

    @property
    def error_cooldown(self):
        """Returns True if the instance was recently set to states.ERROR state.
        """
        if self.last_error and self.state == states.ERROR:
            seconds_since_error = (
                datetime.utcnow() - self.last_error
            ).total_seconds()
            if seconds_since_error < cfg.CONF.error_state_cooldown:
                return True
        return False

    @synchronize_driver_state
    @ensure_cache
    def stop(self, worker_context):
        """Attempts to destroy the instance cluster

        :param worker_context:
        :returns:
        """
        self.log.info(_LI('Destroying instance'))

        self.resource.delete_ports(worker_context)

        if not self.instances:
            self.log.info(_LI('Instance(s) already destroyed.'))
            if self.state != states.GONE:
                self.state = states.DOWN
            return self.state

        try:
            self.instances.destroy(worker_context)
            if self.state != states.GONE:
                self.state = states.DOWN
        except Exception:
            self.log.exception(_LE('Failed to stop instance(s)'))

    @synchronize_driver_state
    @ensure_cache
    def configure(self, worker_context):
        """Pushes config to instance

        :param worker_context:
        :param failure_state:
        :param attempts:
        :returns:
        """
        self.log.debug('Begin instance config')
        self.state = states.UP

        if self.resource.get_state(worker_context) == states.GONE:
            return states.GONE

        if not self.instances.verify_interfaces(self.resource.ports):
            # XXX Need to acct for degraded cluster /w subset of nodes
            # having incorrect plugging.
            self.log.debug("Interfaces aren't plugged as expected.")
            self.state = states.REPLUG
            return self.state

        self.state = self.instances.configure(worker_context)
        return self.state

    def replug(self, worker_context):

        """Attempts to replug the network ports for an instance.

        :param worker_context:
        :returns:
        """
        self.log.debug('Attempting to replug...')

        self.resource.pre_plug(worker_context)

        for instance, interfaces in self.instances.get_interfaces().items():
            actual_macs = set((iface['lladdr'] for iface in interfaces))
            instance_macs = set(p.mac_address for p in instance.ports)
            instance_macs.add(instance.management_port.mac_address)

            if instance_macs != actual_macs:
                # our cached copy of the ports is wrong reboot and clean up
                self.log.warning((
                    'Instance macs(%s) do not match actual macs (%s). Instance'
                    ' cache appears out-of-sync'),
                    instance_macs, actual_macs
                )
                self.state = states.RESTART
                return

            instance_ports = {p.network_id: p for p in instance.ports}
            instance_networks = set(instance_ports.keys())

            logical_networks = set(p.network_id for p in self.resource.ports)

            if logical_networks != instance_networks:
                nova_instance = worker_context.nova_client.get_instance_by_id(
                    instance.id_
                )

                # For each port that doesn't have a mac address on the instance
                for network_id in logical_networks - instance_networks:
                    port = worker_context.neutron.create_vrrp_port(
                        self.resource.id,
                        network_id
                    )
                    self.log.debug(
                        'Net %s is missing from the appliance instance %s, '
                        'plugging: %s', network_id, instance.id_, port.id
                    )

                    try:
                        nova_instance.interface_attach(port.id, None, None)
                        instance.ports.append(port)
                    except:
                        self.log.exception(
                            'Interface attach failed on instance %s',
                            instance.id_)
                        self.instances.remove(worker_context, instance)

            # instance has been removed for failure, do not continue with
            # plugging
            if instance not in self.instances.values():
                continue

            for network_id in instance_networks - logical_networks:
                port = instance_ports[network_id]
                self.log.debug(
                    'Net %s is detached from the router, unplugging: %s',
                    network_id, port.id
                )

                try:
                    nova_instance.interface_detach(port.id)
                    instance.ports.remove(port)
                except:
                    self.log.exception(
                        'Interface detach failed on instance %s',
                        instance.id_)
                    self.instances.remove(worker_context, instance)

            # instance has been removed for failure, do not continue with
            # plugging
            if instance not in self.instances.values():
                continue

            if self._wait_for_interface_hotplug(instance) is not True:
                self.instances.remove(worker_context, instance)

        if not self.instances:
            # all instances were destroyed for plugging failure
            self.state = states.RESTART
        elif self.instances.cluster_degraded:
            # some instances were destroyed for plugging failure
            self.state = states.DEGRADED
        else:
            # plugging was successful
            return

    def _wait_for_interface_hotplug(self, instance):
        """Waits for instance to report interfaces for all expected ports"""
        # The action of attaching/detaching interfaces in Nova happens via
        # the message bus and is *not* blocking.  We need to wait a few
        # seconds to if the list of tap devices on the appliance actually
        # changed.  If not, assume the hotplug failed, and reboot the
        # Instance.
        for i in six.moves.range(1, cfg.CONF.hotplug_timeout):
            self.log.debug(
                "Waiting for interface attachments to take effect..."
            )
            interfaces = self.resource.get_interfaces(
                instance.management_address)

            actual_macs = set((iface['lladdr'] for iface in interfaces))
            instance_macs = set(p.mac_address for p in instance.ports)
            instance_macs.add(instance.management_port.mac_address)
            if actual_macs == instance_macs:
                return True
            time.sleep(1)
        else:
            self.log.debug(
                "Interfaces aren't plugged as expected on instance %s, ",
                "marking for rebooting.", instance.id_)
        return False

    def _check_boot_timeout(self):
        """If the instance was created more than `boot_timeout` seconds
        ago, log an error and set the state set to states.DOWN
        """
        time_since_boot = self.instance_info.time_since_boot

        if time_since_boot:
            if time_since_boot.seconds < cfg.CONF.boot_timeout:
                # Do not reset the state if we have an error
                # condition already. The state will be reset when
                # the router starts responding again, or when the
                # error is cleared from a forced rebuild.
                if self.state != states.ERROR:
                    self.state = states.BOOTING
            else:
                # If the instance was created more than `boot_timeout` seconds
                # ago, log an error and set the state set to states.DOWN
                self.log.info(
                    'Router is DOWN.  Created over %d secs ago.',
                    cfg.CONF.boot_timeout)
                # Do not reset the state if we have an error condition
                # already. The state will be reset when the router starts
                # responding again, or when the error is cleared from a
                # forced rebuild.
                if self.state != states.ERROR:
                    self.state = states.DOWN
