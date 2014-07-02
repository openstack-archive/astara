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
import netaddr
import time

from oslo.config import cfg

from akanda.rug.api import configuration
from akanda.rug.api import akanda_client as router_api
from akanda.rug.api import quantum

DOWN = 'down'
BOOTING = 'booting'
UP = 'up'
CONFIGURED = 'configured'
RESTART = 'restart'
GONE = 'gone'
ERROR = 'error'


def synchronize_router_status(f):
    @wraps(f)
    def wrapper(self, worker_context, silent=False):
        val = f(self, worker_context, silent)
        status_map = {
            DOWN: quantum.STATUS_DOWN,
            BOOTING: quantum.STATUS_BUILD,
            UP: quantum.STATUS_BUILD,
            CONFIGURED: quantum.STATUS_ACTIVE,
            ERROR: quantum.STATUS_ERROR,
        }
        worker_context.neutron.update_router_status(
            self.router_obj.id,
            status_map.get(self.state, quantum.STATUS_ERROR)
        )
        return val
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


class VmManager(object):

    def __init__(self, router_id, tenant_id, log, worker_context):
        self.router_id = router_id
        self.tenant_id = tenant_id
        self.log = log
        self.state = DOWN
        self.router_obj = None
        self.last_boot = None
        self.last_error = None
        self._boot_counter = BootAttemptCounter()
        self._currently_booting = False
        self.update_state(worker_context, silent=True)

    @property
    def attempts(self):
        return self._boot_counter.count

    @synchronize_router_status
    def update_state(self, worker_context, silent=False):
        self._ensure_cache(worker_context)
        if self.state == GONE:
            self.log.debug('not updating state of deleted router')
            return self.state

        if self.router_obj.management_port is None:
            self.log.debug('no management port, marking router as down')
            self.state = DOWN
            return self.state

        addr = _get_management_address(self.router_obj)
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
        if self._currently_booting and self.state == CONFIGURED:
            # If we didn't boot the server (because we were restarted
            # while it remained running, for example), we won't have a
            # last_boot time to log.
            if self.last_boot:
                boot_duration = (datetime.utcnow() - self.last_boot)
                self.log.info('Router booted in %s seconds after %s attempts',
                              boot_duration.total_seconds(),
                              self._boot_counter.count)
            # Always reset the boot counter, even if we didn't boot
            # the server ourself, so we don't accidentally think we
            # have an erroring router.
            self._boot_counter.reset()
            # We've reported how long it took to boot and reset the
            # counter, so we are no longer "currently" booting.
            self._currently_booting = False
        return self.state

    def boot(self, worker_context):
        self._ensure_cache(worker_context)
        if self.state == GONE:
            self.log.info('not booting deleted router')
            return

        self.log.info('Booting router')
        self.state = DOWN
        self._boot_counter.start()

        try:
            self._ensure_provider_ports(self.router_obj, worker_context)

            # In the event that the current akanda instance isn't deleted
            # cleanly (which we've seen in certain circumstances, like
            # hypervisor failures), be proactive and attempt to clean up the
            # router ports manually.  This helps avoid a situation where the
            # rug repeatedly attempts to plug stale router ports into the newly
            # created akanda instance (and fails).
            router = self.router_obj
            instance = worker_context.nova_client.get_instance(router)
            if instance is not None:
                for p in router.ports:
                    if p.device_id == instance.id:
                        worker_context.neutron.clear_device_id(p)
            created = worker_context.nova_client.reboot_router_instance(router)
            if not created:
                self.log.info('Previous router is deleting')
                return
        except:
            self.log.exception('Router failed to start boot')
            return
        else:
            # We have successfully started a (re)boot attempt so
            # record the timestamp so we can report how long it takes.
            self.last_boot = datetime.utcnow()
            self._currently_booting = True

    def check_boot(self, worker_context):
        ready_states = (UP, CONFIGURED)
        if self.update_state(worker_context, silent=True) in ready_states:
            self.log.info('Router has booted, attempting initial config')
            self.configure(worker_context, BOOTING, attempts=1)
            if self.state != CONFIGURED:
                self._check_boot_timeout()
            return self.state == CONFIGURED
        self.log.debug('Router is %s' % self.state.upper())
        return False

    @synchronize_router_status
    def set_error(self, worker_context, silent=False):
        """Set the internal and neutron status for the router to ERROR.

        This is called from outside when something notices the router
        is "broken". We don't use it internally because this class is
        supposed to do what it's told and not make decisions about
        whether or not the router is fatally broken.
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
        # Returns True if the router was recently set to ERROR state.
        if self.last_error:
            seconds_since_error = (
                datetime.utcnow() - self.last_error
            ).total_seconds()
            if seconds_since_error < cfg.CONF.error_state_cooldown:
                return True
        return False

    def stop(self, worker_context):
        self._ensure_cache(worker_context)
        if self.state == GONE:
            # We are being told to delete a router that neutron has
            # already removed. Make a fake router object to use in
            # this method.
            router_obj = quantum.Router(
                id_=self.router_id,
                tenant_id=self.tenant_id,
                name='unnamed',
                admin_state_up=False,
            )
            self.log.info('Destroying router neutron has deleted')
        else:
            router_obj = self.router_obj
            self.log.info('Destroying router')

        nova_client = worker_context.nova_client
        nova_client.destroy_router_instance(router_obj)

        start = time.time()
        while time.time() - start < cfg.CONF.boot_timeout:
            if not nova_client.get_router_instance_status(router_obj):
                if self.state != GONE:
                    self.state = DOWN
                return
            self.log.debug('Router has not finished stopping')
            time.sleep(cfg.CONF.retry_delay)
        self.log.error(
            'Router failed to stop within %d secs',
            cfg.CONF.boot_timeout)

    def configure(self, worker_context, failure_state=RESTART, attempts=None):
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

        addr = _get_management_address(self.router_obj)

        # FIXME: This should raise an explicit exception so the caller
        # knows that we could not talk to the router (versus the issue
        # above).
        interfaces = router_api.get_interfaces(
            addr,
            cfg.CONF.akanda_mgt_service_port
        )

        if not self._verify_interfaces(self.router_obj, interfaces):
            # FIXME: Need a REPLUG state when we support hot-plugging
            # interfaces.
            self.log.debug("Interfaces aren't plugged as expected, rebooting.")
            self.state = RESTART
            return

        # FIXME: Need to catch errors talking to neutron here.
        config = configuration.build_config(
            worker_context.neutron,
            self.router_obj,
            interfaces
        )
        self.log.debug('preparing to update config to %r', config)

        for i in xrange(attempts):
            try:
                router_api.update_config(
                    addr,
                    cfg.CONF.akanda_mgt_service_port,
                    config
                )
            except Exception:
                if i == attempts - 1:
                    # Only log the traceback if we encounter it many times.
                    self.log.exception('failed to update config')
                else:
                    self.log.debug(
                        'failed to update config, attempt %d',
                        i
                    )
                time.sleep(cfg.CONF.retry_delay)
            else:
                self.state = CONFIGURED
                self.log.info('Router config updated')
                return
        else:
            # FIXME: We failed to configure the router too many times,
            # so restart it.
            self.state = failure_state

    def _ensure_cache(self, worker_context):
        try:
            self.router_obj = worker_context.neutron.get_router_detail(
                self.router_id
            )
        except quantum.RouterGone:
            # The router has been deleted, set our state accordingly
            # and return without doing any more work.
            self.state = GONE
            self.router_obj = None

    def _check_boot_timeout(self):
        if self.last_boot:
            seconds_since_boot = (
                datetime.utcnow() - self.last_boot
            ).total_seconds()
            if seconds_since_boot < cfg.CONF.boot_timeout:
                # Do not reset the state if we have an error
                # condition already. The state will be reset when
                # the router starts responding again, or when the
                # error is cleared from a forced rebuild.
                if self.state != ERROR:
                    self.state = BOOTING
            else:
                # If the VM was created more than `boot_timeout` seconds
                # ago, log an error and set the state set to DOWN
                self.last_boot = None
                self._currently_booting = False
                self.log.info(
                    'Router is DOWN.  Created over %d secs ago.',
                    cfg.CONF.boot_timeout)
                # Do not reset the state if we have an error condition
                # already. The state will be reset when the router starts
                # responding again, or when the error is cleared from a
                # forced rebuild.
                if self.state != ERROR:
                    self.state = DOWN

    def _verify_interfaces(self, logical_config, interfaces):
        router_macs = set((iface['lladdr'] for iface in interfaces))
        self.log.debug('MACs found: %s', ', '.join(sorted(router_macs)))

        if not all(
            getattr(p, 'mac_address', None) for p in logical_config.ports
        ):
            return False

        expected_macs = set(p.mac_address
                            for p in logical_config.internal_ports)
        expected_macs.add(logical_config.management_port.mac_address)
        expected_macs.add(logical_config.external_port.mac_address)
        self.log.debug('MACs expected: %s', ', '.join(sorted(expected_macs)))

        return router_macs == expected_macs

    def _ensure_provider_ports(self, router, worker_context):
        if router.management_port is None:
            self.log.debug('Adding management port to router')
            mgt_port = worker_context.neutron.create_router_management_port(
                router.id
            )
            router.management_port = mgt_port

        if router.external_port is None:
            # FIXME: Need to do some work to pick the right external
            # network for a tenant.
            self.log.debug('Adding external port to router')
            ext_port = worker_context.neutron.create_router_external_port(
                router
            )
            router.external_port = ext_port
        return router


def _get_management_address(router):
    network = netaddr.IPNetwork(cfg.CONF.management_prefix)

    tokens = ['%02x' % int(t, 16)
              for t in router.management_port.mac_address.split(':')]
    eui64 = int(''.join(tokens[0:3] + ['ff', 'fe'] + tokens[3:6]), 16)

    # the bit inversion is required by the RFC
    return str(netaddr.IPAddress(network.value + (eui64 ^ 0x0200000000000000)))
