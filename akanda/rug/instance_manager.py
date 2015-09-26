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

from oslo_config import cfg

from akanda.rug.api import configuration
from akanda.rug.api import akanda_client as router_api
from akanda.rug.api import neutron
from akanda.rug.common.i18n import _LE, _LI, _LW

DOWN = 'down'
BOOTING = 'booting'
UP = 'up'
CONFIGURED = 'configured'
RESTART = 'restart'
REPLUG = 'replug'
GONE = 'gone'
ERROR = 'error'

STATUS_MAP = {
    DOWN: neutron.STATUS_DOWN,
    BOOTING: neutron.STATUS_BUILD,
    UP: neutron.STATUS_BUILD,
    CONFIGURED: neutron.STATUS_ACTIVE,
    ERROR: neutron.STATUS_ERROR,
}


CONF = cfg.CONF
INSTANCE_MANAGER_OPTS = [
    cfg.IntOpt(
        'hotplug_timeout', default=10,
        help='The amount of time to wait for nova to hotplug/unplug '
        'networks from the router instances'),
    cfg.IntOpt(
        'boot_timeout', default=600),
    cfg.IntOpt(
        'error_state_cooldown',
        default=30,
        help=('Number of seconds to ignore new events when a router goes '
              'into ERROR state'),
    ),
]
CONF.register_opts(INSTANCE_MANAGER_OPTS)


def synchronize_router_status(f):
    @wraps(f)
    def wrapper(self, worker_context, silent=False):
        old_status = self._last_synced_status
        val = f(self, worker_context, silent)
        if not self.router_obj:
            return val
        new_status = STATUS_MAP.get(self.state, neutron.STATUS_ERROR)
        if not old_status or old_status != new_status:
            worker_context.neutron.update_router_status(
                self.router_obj.id,
                new_status
            )
            self._last_synced_status = new_status
        return val
    return wrapper


class BootAttemptCounter(object):
    def __init__(self):
        """Initializes the boot counter

        :returns: returns nothing
        """
        self._attempts = 0

    def start(self):
        """Increments the Boot Attempt Counter

        :returns: returns nothing
        """
        self._attempts += 1

    def reset(self):
        """Resets the Boot Attempt Counter

        :returns: returns nothing
        """
        self._attempts = 0

    @property
    def count(self):
        """Boot Attempt Counter Property

        :returns: returns a count of the number of boot attempts
        """
        return self._attempts


class InstanceManager(object):

    def __init__(self, router_id, tenant_id, log, worker_context):
        self.router_id = router_id
        self.tenant_id = tenant_id
        self.log = log
        self.state = DOWN
        self.router_obj = None
        self.instance_info = None
        self.last_error = None
        self._boot_counter = BootAttemptCounter()
        self._last_synced_status = None
        self.update_state(worker_context, silent=True)

    @property
    def attempts(self):
        """Returns the number of attempts this Instance has attempted to boot.

        :returns: returns the number of attempts this instance has attempted to
            boot
        """
        return self._boot_counter.count

    def reset_boot_counter(self):
        """Resets the number of attempts this Instance has attempted to boot.

        :returns: returns nothing
        """
        self._boot_counter.reset()

    @synchronize_router_status
    def update_state(self, worker_context, silent=False):
        """Updates the status of a particular instance

        :param worker_context: The WorkerContext of the instance
        :param silent: sets the verbosity of this function during it's Alive
            Check
        :returns: the updated state
        """
        self._ensure_cache(worker_context)
        if self.state == GONE:
            self.log.debug('not updating state of deleted router')
            return self.state

        if self.instance_info is None:
            self.log.debug('no backing instance, marking router as down')
            self.state = DOWN
            return self.state

        addr = self.instance_info.management_address
        for i in xrange(cfg.CONF.max_retries):
            if router_api.is_alive(addr, cfg.CONF.akanda_mgt_service_port):
                if self.state != CONFIGURED:
                    self.state = UP
                break
            if not silent:
                self.log.debug(
                    'Alive check failed. Attempt %d of %d',
                    i,
                    cfg.CONF.max_retries,
                )
            time.sleep(cfg.CONF.retry_delay)
        else:
            old_state = self.state
            self._check_boot_timeout()

            # If the router isn't responding, make sure Nova knows about it
            instance = worker_context.nova_client.get_instance_for_obj(
                self.router_id
            )
            if instance is None and self.state != ERROR:
                self.log.info(_LI('No instance was found; rebooting'))
                self.state = DOWN
                self.instance_info = None

            # update_state() is called from Alive() to check the
            # status of the router. If we can't talk to the API at
            # that point, the router should be considered missing and
            # we should reboot it, so mark it down if we think it was
            # configured before.
            if old_state == CONFIGURED and self.state != ERROR:
                self.log.debug(
                    'Did not find router alive, marking it as down',
                )
                self.state = DOWN

        # After the router is all the way up, record how long it took
        # to boot and accept a configuration.
        if self.instance_info.booting and self.state == CONFIGURED:
            # If we didn't boot the server (because we were restarted
            # while it remained running, for example), we won't have a
            # duration to log.
            self.instance_info.confirm_up()
            if self.instance_info.boot_duration:
                self.log.info(
                    _LI('Router booted in %s seconds after %s attempts'),
                    self.instance_info.boot_duration.total_seconds(),
                    self._boot_counter.count)
            # Always reset the boot counter, even if we didn't boot
            # the server ourself, so we don't accidentally think we
            # have an erroring router.
            self._boot_counter.reset()
        return self.state

    def boot(self, worker_context, router_image_uuid):
        """Attempt to boot an instance

        :param worker_context:  The WorkerContext of the instance
        :param router_image_uuid: Glance UUID for the image to boot
        :returns: returns nothing
        """
        self._ensure_cache(worker_context)
        if self.state == GONE:
            self.log.info(_LI('Not booting deleted router'))
            return

        self.log.info(_LI('Booting router'))
        self.state = DOWN
        self._boot_counter.start()

        def make_vrrp_ports():
            mgt_port = worker_context.neutron.create_management_port(
                self.router_obj.id
            )

            # FIXME(mark): ideally this should be ordered and de-duped
            instance_ports = [
                worker_context.neutron.create_vrrp_port(self.router_obj.id, n)
                for n in (p.network_id for p in self.router_obj.ports)
            ]

            return mgt_port, instance_ports

        try:
            # TODO(mark): make this pluggable
            self._ensure_provider_ports(self.router_obj, worker_context)

            # TODO(mark): make this handle errors more gracefully on cb fail
            # TODO(mark): checkout from a pool - boot on demand for now
            instance_info = worker_context.nova_client.boot_instance(
                self.instance_info,
                self.router_obj.id,
                router_image_uuid,
                make_vrrp_ports
            )
            if not instance_info:
                self.log.info(_LI('Previous router is deleting'))
                # Reset the VM manager, causing the state machine to start
                # again with a new VM.
                self.reset_boot_counter()
                self.instance_info = None
                return
        except:
            self.log.exception(_LE('Router failed to start boot'))
            # TODO(mark): attempt clean-up of failed ports
            return
        else:
            # We have successfully started a (re)boot attempt so
            # record the timestamp so we can report how long it takes.
            self.state = BOOTING
            self.instance_info = instance_info

    def check_boot(self, worker_context):
        ready_states = (UP, CONFIGURED)
        if self.update_state(worker_context, silent=True) in ready_states:
            self.log.info(_LI('Router has booted, attempting initial config'))
            self.configure(worker_context, BOOTING, attempts=1)
            if self.state != CONFIGURED:
                self._check_boot_timeout()
            return self.state == CONFIGURED

        self.log.debug('Router is %s', self.state.upper())
        return False

    @synchronize_router_status
    def set_error(self, worker_context, silent=False):
        """Set the internal and neutron status for the router to ERROR.

        This is called from outside when something notices the router
        is "broken". We don't use it internally because this class is
        supposed to do what it's told and not make decisions about
        whether or not the router is fatally broken.

        :param worker_context: The WorkerContext of the instance
        :param slient: currently ignored
        :returns: updated state
        """
        self._ensure_cache(worker_context)
        if self.state == GONE:
            self.log.debug('not updating state of deleted router')
            return self.state
        self.state = ERROR
        self.last_error = datetime.utcnow()
        return self.state

    @synchronize_router_status
    def clear_error(self, worker_context, silent=False):
        """Clear the internal error state.

        This is called from outside when something wants to force a
        router rebuild, so that the state machine that checks our
        status won't think we are broken unless we actually break
        again.

        :param worker_context: The WorkerContext of the instance
        :param silent: currently ignored
        :returns: updated state
        """
        # Clear the boot counter.
        self._boot_counter.reset()
        self._ensure_cache(worker_context)
        if self.state == GONE:
            self.log.debug('not updating state of deleted router')
            return self.state
        self.state = DOWN
        return self.state

    @property
    def error_cooldown(self):
        """Check if there was recently an error.

        :returns: Returns True if the router was recently set to ERROR state.
        """
        if self.last_error and self.state == ERROR:
            seconds_since_error = (
                datetime.utcnow() - self.last_error
            ).total_seconds()
            if seconds_since_error < cfg.CONF.error_state_cooldown:
                return True
        return False

    def stop(self, worker_context):
        """Stop an instance.

        :params worker_context: The WorkerContext of the instance
        :returns: returns nothing
        """
        self._ensure_cache(worker_context)
        if self.state == GONE:
            self.log.info(_LI('Destroying router neutron has deleted'))
        else:
            self.log.info(_LI('Destroying router'))

        try:
            nova_client = worker_context.nova_client
            nova_client.destroy_instance(self.instance_info)
        except Exception:
            self.log.exception(_LE('Error deleting router instance'))

        start = time.time()
        while time.time() - start < cfg.CONF.boot_timeout:
            if not nova_client.get_instance_by_id(self.instance_info.id_):
                if self.state != GONE:
                    self.state = DOWN
                return
            self.log.debug('Router has not finished stopping')
            time.sleep(cfg.CONF.retry_delay)
        self.log.error(_LE(
            'Router failed to stop within %d secs'),
            cfg.CONF.boot_timeout)

    def configure(self, worker_context, failure_state=RESTART, attempts=None):
        """Configures a booted instance

        :params worker_context: The WorkerContext of the instance
        :params failure_state: State to return to if we fail to configure
        :params attempts: Number of attempts to try to configure
        :returns: returns nothing
        """
        self.log.debug('Begin router config')
        self.state = UP
        attempts = attempts or cfg.CONF.max_retries

        # FIXME: This might raise an error, which doesn't mean the
        # *router* is broken, but does mean we can't update it.
        # Change the exception to something the caller can catch
        # safely.
        self._ensure_cache(worker_context)
        if self.state == GONE:
            return

        # FIXME: This should raise an explicit exception so the caller

        # knows that we could not talk to the router (versus the issue
        # above).
        interfaces = router_api.get_interfaces(
            self.instance_info.management_address,
            cfg.CONF.akanda_mgt_service_port
        )

        if not self._verify_interfaces(self.router_obj, interfaces):
            # FIXME: Need a REPLUG state when we support hot-plugging
            # interfaces.
            self.log.debug("Interfaces aren't plugged as expected.")
            self.state = REPLUG
            return

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

        # FIXME: Need to catch errors talking to neutron here.
        config = configuration.build_config(
            worker_context.neutron,
            self.router_obj,
            mgt_port,
            iface_map
        )
        self.log.debug('preparing to update config to %r', config)

        for i in xrange(attempts):
            try:
                router_api.update_config(
                    self.instance_info.management_address,
                    cfg.CONF.akanda_mgt_service_port,
                    config
                )
            except Exception:
                if i == attempts - 1:
                    # Only log the traceback if we encounter it many times.
                    self.log.exception(_LE('Failed to update config'))
                else:
                    self.log.debug(
                        'failed to update config, attempt %d',
                        i
                    )
                time.sleep(cfg.CONF.retry_delay)
            else:
                self.state = CONFIGURED
                self.log.info(_LI('Router config updated'))
                return
        else:
            # FIXME: We failed to configure the router too many times,
            # so restart it.
            self.state = failure_state

    def replug(self, worker_context):
        """Attempt to replug this instance's interfaces

        :params worker_context: The WorkerContext of the instance
        :returns: returns nothing
        """
        self.log.debug('Attempting to replug...')
        self._ensure_provider_ports(self.router_obj, worker_context)

        interfaces = router_api.get_interfaces(
            self.instance_info.management_address,
            cfg.CONF.akanda_mgt_service_port
        )
        actual_macs = set((iface['lladdr'] for iface in interfaces))
        instance_macs = set(p.mac_address for p in self.instance_info.ports)
        instance_macs.add(self.instance_info.management_port.mac_address)

        if instance_macs != actual_macs:
            # our cached copy of the ports is wrong reboot and clean up
            self.log.warning(
                _LW('Instance macs(%s) do not match actual macs (%s). '
                    'Instance cache appears out-of-sync'),
                instance_macs, actual_macs
            )
            self.state = RESTART
            return

        instance_ports = {p.network_id: p for p in self.instance_info.ports}
        instance_networks = set(instance_ports.keys())

        logical_networks = set(p.network_id for p in self.router_obj.ports)

        if logical_networks != instance_networks:
            instance = worker_context.nova_client.get_instance_by_id(
                self.instance_info.id_
            )

            # For each port that doesn't have a mac address on the instance...
            for network_id in logical_networks - instance_networks:
                port = worker_context.neutron.create_vrrp_port(
                    self.router_obj.id,
                    network_id
                )
                self.log.debug(
                    'Net %s is missing from the router, plugging: %s',
                    network_id, port.id
                )

                try:
                    instance.interface_attach(port.id, None, None)
                except:
                    self.log.exception(_LE('Interface attach failed'))
                    self.state = RESTART
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
                    self.log.exception(_LE('Interface detach failed'))
                    self.state = RESTART
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
            interfaces = router_api.get_interfaces(
                self.instance_info.management_address,
                cfg.CONF.akanda_mgt_service_port
            )
            if self._verify_interfaces(self.router_obj, interfaces):
                # replugging was successful
                # TODO(mark) update port states
                return
            time.sleep(1)
            replug_seconds -= 1

        self.log.debug("Interfaces aren't plugged as expected, rebooting.")
        self.state = RESTART

    def _ensure_cache(self, worker_context):
        """Set all Instance cache data from primary sources.

        :params worker_context: The WorkerContext of the instance
        :returns: returns nothing
        """
        try:
            self.router_obj = worker_context.neutron.get_router_detail(
                self.router_id
            )
        except neutron.RouterGone:
            # The router has been deleted, set our state accordingly
            # and return without doing any more work.
            self.state = GONE
            self.router_obj = None

        if not self.instance_info:
            self.instance_info = (
                worker_context.nova_client.get_instance_info_for_obj(
                    self.router_id
                )
            )

            if self.instance_info:
                (
                    self.instance_info.management_port,
                    self.instance_info.ports
                ) = worker_context.neutron.get_ports_for_instance(
                    self.instance_info.id_
                )

    def _check_boot_timeout(self):
        """Check to see if this instance has taken too long to boot

        :returns: returns nothing
        """
        time_since_boot = self.instance_info.time_since_boot

        if time_since_boot:
            if time_since_boot.seconds < cfg.CONF.boot_timeout:
                # Do not reset the state if we have an error
                # condition already. The state will be reset when
                # the router starts responding again, or when the
                # error is cleared from a forced rebuild.
                if self.state != ERROR:
                    self.state = BOOTING
            else:
                # If the instance was created more than `boot_timeout` seconds
                # ago, log an error and set the state set to DOWN
                self.log.info(
                    _LI('Router is DOWN.  Created over %d secs ago.'),
                    cfg.CONF.boot_timeout)
                # Do not reset the state if we have an error condition
                # already. The state will be reset when the router starts
                # responding again, or when the error is cleared from a
                # forced rebuild.
                if self.state != ERROR:
                    self.state = DOWN

    def _verify_interfaces(self, logical_config, interfaces):
        """Validate that the port counts match.

        :returns: True if the interface accounting adds up
        """
        router_macs = set((iface['lladdr'] for iface in interfaces))
        self.log.debug('MACs found: %s', ', '.join(sorted(router_macs)))

        if not all(
            getattr(p, 'mac_address', None) for p in logical_config.ports
        ):
            return False

        num_logical_ports = len(list(logical_config.ports))
        num_instance_ports = len(list(self.instance_info.ports))
        if num_logical_ports != num_instance_ports:
            return False

        expected_macs = set(p.mac_address
                            for p in self.instance_info.ports)
        expected_macs.add(self.instance_info.management_port.mac_address)
        self.log.debug('MACs expected: %s', ', '.join(sorted(expected_macs)))

        return router_macs == expected_macs

    def _ensure_provider_ports(self, router, worker_context):
        """Validate and set the external port of the router

        :param router: the router being checked
        :params worker_context: The WorkerContext of the instance
        :returns: router
        """
        if router.external_port is None:
            # FIXME: Need to do some work to pick the right external
            # network for a tenant.
            self.log.debug('Adding external port to router')
            ext_port = worker_context.neutron.create_router_external_port(
                router
            )
            router.external_port = ext_port
        return router
