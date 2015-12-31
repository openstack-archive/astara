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
import time

from oslo_config import cfg

from astara.drivers import states
from astara.common.i18n import _LE, _LI

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


def synchronize_driver_state(f):
    """Wrapper that triggers a driver's synchronize_state function"""
    def wrapper(self, *args, **kw):
        state = f(self, *args, **kw)
        self.driver.synchronize_state(*args, state=state)
        return state
    return wrapper


def ensure_cache(f):
    """Decorator to wrap around any function that uses self.instance_info.

    Insures that self.instance_info is up to date and catches instances in a
    GONE or missing state before wasting cycles trying to do something with it.

    NOTE: This replaces the old function called _ensure_cache made a Decorator
    rather than calling it explicitly at the start of all those functions.
    """
    def wrapper(self, worker_context, *args, **kw):
        # insure that self.instance_info is current before doing anything.
        if not self.instance_info:
            # attempt to populate instance_info
            self.instance_info = (
                worker_context.nova_client.get_instance_info(self.driver.name)
            )

            if self.instance_info:
                (
                    self.instance_info.management_port,
                    self.instance_info.ports
                ) = worker_context.neutron.get_ports_for_instance(
                    self.instance_info.id_
                )

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


class InstanceManager(object):

    def __init__(self, driver, resource_id, worker_context):
        """The instance manager is your interface to the running instance.
        wether it be virtual, container or physical.

        Service specific code lives in the driver which is passed in here.

        :param driver: driver object
        :param resource_id: UUID of logical resource
        :param worker_context:
        """
        self.driver = driver
        self.id = resource_id
        self.log = self.driver.log

        self.state = states.DOWN

        self.instance_info = None
        self.last_error = None
        self._boot_counter = BootAttemptCounter()
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
    def update_state(self, worker_context, silent=False):
        """Updates state of the instance and, by extension, its logical resource

        :param worker_context:
        :param silent:
        :returns: state
        """
        self._ensure_cache(worker_context)

        if self.driver.get_state(worker_context) == states.GONE:
            self.log.debug('%s driver reported its state is GONE',
                           self.driver.RESOURCE_NAME)
            self.state = states.GONE
            return self.state

        if self.instance_info is None:
            self.log.info(_LI('no backing instance, marking as down'))
            self.state = states.DOWN
            return self.state

        addr = self.instance_info.management_address
        if not addr:
            self.log.debug('waiting for instance ports to be attached')
            self.state = states.BOOTING
            return self.state

        for i in xrange(cfg.CONF.max_retries):
            if self.driver.is_alive(self.instance_info.management_address):
                if self.state != states.CONFIGURED:
                    self.state = states.UP
                break
            if not silent:
                self.log.debug('Alive check failed. Attempt %d of %d',
                               i,
                               cfg.CONF.max_retries)
            time.sleep(cfg.CONF.retry_delay)
        else:
            old_state = self.state
            self._check_boot_timeout()

            # If the instance isn't responding, make sure Nova knows about it
            instance = worker_context.nova_client.get_instance_for_obj(self.id)
            if instance is None and self.state != states.ERROR:
                self.log.info(_LI('No instance was found; rebooting'))
                self.state = states.DOWN
                self.instance_info = None

            # update_state() is called from Alive() to check the
            # status of the router. If we can't talk to the API at
            # that point, the router should be considered missing and
            # we should reboot it, so mark it states.DOWN if we think it was
            # configured before.
            if old_state == states.CONFIGURED and self.state != states.ERROR:
                self.log.debug('Instance not alive, marking it as DOWN')
                self.state = states.DOWN

        # After the instance is all the way up, record how long it took
        # to boot and accept a configuration.
        self.instance_info = (
            worker_context.nova_client.update_instance_info(
                self.instance_info))

        if not self.instance_info.booting and self.state == states.CONFIGURED:
            # If we didn't boot the server (because we were restarted
            # while it remained running, for example), we won't have a
            # duration to log.
            self.log.info(_LI('%s booted in %s seconds after %s attempts'),
                          self.driver.RESOURCE_NAME,
                          self.instance_info.time_since_boot.total_seconds(),
                          self._boot_counter.count)

            # Always reset the boot counter, even if we didn't boot
            # the server ourself, so we don't accidentally think we
            # have an erroring router.
            self._boot_counter.reset()
        return self.state

    def boot(self, worker_context):
        """Boots the instance with driver pre/post boot hooks.

        :returns: None
        """
        self._ensure_cache(worker_context)

        self.log.info(_LI('Booting %s') % self.driver.RESOURCE_NAME)
        self.state = states.DOWN
        self._boot_counter.start()

        # driver preboot hook
        self.driver.pre_boot(worker_context)

        # try to boot the instance
        try:
            instance_info = worker_context.nova_client.boot_instance(
                resource_type=self.driver.RESOURCE_NAME,
                prev_instance_info=self.instance_info,
                name=self.driver.name,
                image_uuid=self.driver.image_uuid,
                flavor=self.driver.flavor,
                make_ports_callback=self.driver.make_ports(worker_context)
            )
            if not instance_info:
                self.log.info(_LI('Previous instance is still deleting'))
                # Reset the boot counter, causing the state machine to start
                # again with a new Instance.
                self.reset_boot_counter()
                self.instance_info = None
                return
        except:
            self.log.exception(_LE('Instance failed to start boot'))
            self.driver.delete_ports(worker_context)
        else:
            # We have successfully started a (re)boot attempt so
            # record the timestamp so we can report how long it takes.
            self.state = states.BOOTING
            self.instance_info = instance_info

        # driver post boot hook
        self.driver.post_boot(worker_context)

    def check_boot(self, worker_context):
        """Checks status of instance, if ready triggers self.configure
        """
        state = self.update_state(worker_context, silent=True)
        if state in states.READY_STATES:
            self.log.info(_LI('Instance has booted, attempting
                          initial config'))
            self.configure(worker_context)
            if self.state != states.CONFIGURED:
                self._check_boot_timeout()
            return self.state == states.CONFIGURED

        self.log.debug('Instance is %s' % self.state.upper())
        return False

    @synchronize_driver_state
    def set_error(self, worker_context, silent=False):
        """Set the internal and neutron status for the router to states.ERROR.

        This is called from outside when something notices the router
        is "broken". We don't use it internally because this class is
        supposed to do what it's told and not make decisions about
        whether or not the router is fatally broken.
        """
        self._ensure_cache(worker_context)
        self.state = states.ERROR
        self.last_error = datetime.utcnow()
        return self.state

    @synchronize_driver_state
    def clear_error(self, worker_context, silent=False):
        """Clear the internal error state.

        This is called from outside when something wants to force a
        router rebuild, so that the state machine that checks our
        status won't think we are broken unless we actually break
        again.
        """
        # Clear the boot counter.
        self._boot_counter.reset()
        self._ensure_cache(worker_context)
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
    def stop(self, worker_context):
        """Attempts to destroy the instance with configured timeout.

        :param worker_context:
        :returns:
        """
        self._ensure_cache(worker_context)
        self.log.info(_LI('Destroying instance'))

        if not self.instance_info:
            self.log.info(_LI('Instance already destroyed.'))
            return states.GONE

        worker_context.neutron.delete_vrrp_port(self.driver.id)
        worker_context.neutron.delete_vrrp_port(self.driver.id, label='MGT')

        try:
            worker_context.nova_client.destroy_instance(self.instance_info)
        except Exception:
            self.log.exception(_LE('Error deleting router instance'))

        start = time.time()
        i = 0
        while time.time() - start < cfg.CONF.boot_timeout:
            i += 1
            if not worker_context.nova_client.\
                    get_instance_by_id(self.instance_info.id_):
                if self.state != states.GONE:
                    self.state = states.DOWN
                return self.state
            self.log.debug('Router has not finished stopping')
            time.sleep(cfg.CONF.retry_delay)
        self.log.error(_LE(
            'Router failed to stop within %d secs'),
            cfg.CONF.boot_timeout)

    @synchronize_driver_state
    def configure(self, worker_context):
        """Pushes config to instance

        :param worker_context:
        :param failure_state:
        :param attempts:
        :returns:
        """
        self.log.debug('Begin instance config')
        self.state = states.UP
        attempts = cfg.CONF.max_retries

        self._ensure_cache(worker_context)
        if self.driver.get_state(worker_context) == states.GONE:
            return states.GONE

        interfaces = self.driver.get_interfaces(
            self.instance_info.management_address)

        if not self._verify_interfaces(self.driver.ports, interfaces):
            # FIXME: Need a states.REPLUG state when we support hot-plugging
            # interfaces.
            self.log.debug("Interfaces aren't plugged as expected.")
            self.state = states.REPLUG
            return self.state

        # TODO(mark): We're in the first phase of VRRP, so we need
        # map the interface to the network ID.
        # Eventually we'll send VRRP data and real interface data
        port_mac_to_net = {
            p.mac_address: p.network_id
            for p in self.instance_info.ports
        }
        # Add in the management port
        mgt_port = self.instance_info.management_port
        port_mac_to_net[mgt_port.mac_address] = mgt_port.network_id
        # this is a network to logical interface id
        iface_map = {
            port_mac_to_net[i['lladdr']]: i['ifname']
            for i in interfaces if i['lladdr'] in port_mac_to_net
        }

        # sending all the standard config over to the driver for final updates
        config = self.driver.build_config(
            worker_context,
            mgt_port,
            iface_map
        )
        self.log.debug('preparing to update config to %r', config)

        for i in xrange(attempts):
            try:
                self.driver.update_config(
                    self.instance_info.management_address,
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
                self.state = states.CONFIGURED
                self.log.info('Instance config updated')
                return self.state
        else:
            self.state = states.RESTART
            return self.state

    def replug(self, worker_context):

        """Attempts to replug the network ports for an instance.

        :param worker_context:
        :returns:
        """
        self.log.debug('Attempting to replug...')

        self.driver.pre_plug(worker_context)

        interfaces = self.driver.get_interfaces(
            self.instance_info.management_address)

        actual_macs = set((iface['lladdr'] for iface in interfaces))
        instance_macs = set(p.mac_address for p in self.instance_info.ports)
        instance_macs.add(self.instance_info.management_port.mac_address)

        if instance_macs != actual_macs:
            # our cached copy of the ports is wrong reboot and clean up
            self.log.warning(
                ('Instance macs(%s) do not match actual macs (%s). Instance '
                 'cache appears out-of-sync'),
                instance_macs, actual_macs
            )
            self.state = states.RESTART
            return

        instance_ports = {p.network_id: p for p in self.instance_info.ports}
        instance_networks = set(instance_ports.keys())

        logical_networks = set(p.network_id for p in self.driver.ports)

        if logical_networks != instance_networks:
            instance = worker_context.nova_client.get_instance_by_id(
                self.instance_info.id_
            )

            # For each port that doesn't have a mac address on the instance...
            for network_id in logical_networks - instance_networks:
                port = worker_context.neutron.create_vrrp_port(
                    self.driver.id,
                    network_id
                )
                self.log.debug(
                    'Net %s is missing from the router, plugging: %s',
                    network_id, port.id
                )

                try:
                    instance.interface_attach(port.id, None, None)
                except:
                    self.log.exception('Interface attach failed')
                    self.state = states.RESTART
                    return
                self.instance_info.ports.append(port)

            for network_id in instance_networks - logical_networks:
                port = instance_ports[network_id]
                self.log.debug(
                    'Net %s is detached from the router, unplugging: %s',
                    network_id, port.id
                )

                try:
                    instance.interface_detach(port.id)
                except:
                    self.log.exception('Interface detach failed')
                    self.state = states.RESTART
                    return

                self.instance_info.ports.remove(port)

        # The action of attaching/detaching interfaces in Nova happens via the
        # message bus and is *not* blocking.  We need to wait a few seconds to
        # see if the list of tap devices on the appliance actually changed.  If
        # not, assume the hotplug failed, and reboot the Instance.
        replug_seconds = cfg.CONF.hotplug_timeout
        while replug_seconds > 0:
            self.log.debug(
                "Waiting for interface attachments to take effect..."
            )
            interfaces = self.driver.get_interfaces(
                self.instance_info.management_address)

            if self._verify_interfaces(self.driver.ports, interfaces):
                # replugging was successful
                # TODO(mark) update port states
                return

            time.sleep(1)
            replug_seconds -= 1

        self.log.debug("Interfaces aren't plugged as expected, rebooting.")
        self.state = states.RESTART

    def _ensure_cache(self, worker_context):
        self.instance_info = (
            worker_context.nova_client.get_instance_info(self.driver.name)
        )

        if self.instance_info:
            (
                self.instance_info.management_port,
                self.instance_info.ports
            ) = worker_context.neutron.get_ports_for_instance(
                self.instance_info.id_
            )

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

    def _verify_interfaces(self, ports, interfaces):
        """Verifies the network interfaces are what they should be.
        """
        actual_macs = set((iface['lladdr'] for iface in interfaces))
        self.log.debug('MACs found: %s', ', '.join(sorted(actual_macs)))
        if not all(
            getattr(p, 'mac_address', None) for p in ports
        ):
            return False

        num_logical_ports = len(list(ports))
        num_instance_ports = len(list(self.instance_info.ports))
        if num_logical_ports != num_instance_ports:
            return False

        expected_macs = set(p.mac_address
                            for p in self.instance_info.ports)
        expected_macs.add(self.instance_info.management_port.mac_address)
        self.log.debug('MACs expected: %s', ', '.join(sorted(expected_macs)))

        return actual_macs == expected_macs
