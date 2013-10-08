import netaddr
import time

from oslo.config import cfg

from akanda.rug.api import configuration
from akanda.rug.api import nova
from akanda.rug.api import quantum
from akanda.rug.api import akanda_client as router_api

DOWN = 'down'
UP = 'up'
CONFIGURED = 'configured'
RESTART = 'restart'

MAX_RETRIES = 3
BOOT_WAIT = 120
RETRY_DELAY = 1


class VmManager(object):
    def __init__(self, router_id, log):
        self.router_id = router_id
        self.log = log
        self.state = DOWN
        self.router_obj = None
        self.quantum = quantum.Quantum(cfg.CONF)

        self.update_state(silent=True)

    def update_state(self, silent=False):
        self._ensure_cache()

        if self.router_obj.management_port is None:
            self.state = DOWN
            return self.state

        addr = _get_management_address(self.router_obj)
        for i in xrange(MAX_RETRIES):
            try:
                if router_api.is_alive(addr, cfg.CONF.akanda_mgt_service_port):
                    if self.state != CONFIGURED:
                        self.state = UP
                    break
            except:
                if not silent:
                    self.log.exception(
                        'Alive check failed. Attempt %d of %d',
                        i,
                        MAX_RETRIES
                    )
                time.sleep(RETRY_DELAY)
        else:
            self.state = DOWN

        return self.state

    def boot(self):
        self.router_obj = self.quantum.get_router_detail(self.router_id)

        self._ensure_provider_ports(self.router_obj)

        self.log.info('Booting router')
        nova_client = nova.Nova(cfg.CONF)
        nova_client.reboot_router_instance(self.router_obj)
        self.state = DOWN

        start = time.time()
        while time.time() - start < BOOT_WAIT:
            if self.update_state(silent=True) in (UP, CONFIGURED):
                return
            self.log.debug('Router has not finished booting')

        self.log.error('Router failed to boot within %d secs', BOOT_WAIT)

    def stop(self):
        self._ensure_cache()
        self.log.info('Destroying router')

        nova_client = nova.Nova(cfg.CONF)
        nova_client.destroy_router_instance(self.router_obj)

        start = time.time()
        while time.time() - start < BOOT_WAIT:
            if not nova_client.get_router_instance_status(self.router_obj):
                self.state = DOWN
                return
            self.log.debug('Router has not finished stopping')
            time.sleep(RETRY_DELAY)
        self.log.error('Router failed to stop within %d secs', BOOT_WAIT)

    def configure(self):
        self.log.debug('Begin router config')
        self.state = UP

        self.router_obj = self.quantum.get_router_detail(self.router_id)

        addr = _get_management_address(self.router_obj)

        interfaces = router_api.get_interfaces(
            addr,
            cfg.CONF.akanda_mgt_service_port
        )

        if not self._verify_interfaces(self.router_obj, interfaces):
            self.state = RESTART
            return

        config = configuration.build_config(
            self.quantum,
            self.router_obj,
            interfaces
        )

        for i in xrange(MAX_RETRIES):
            try:
                router_api.update_config(
                    addr,
                    cfg.CONF.akanda_mgt_service_port,
                    config
                )
            except Exception:
                self.log.exception('failed to update config')
                time.sleep(i + 1)
            else:
                self.state = CONFIGURED
                self.log.debug('Router config updated')
                return

    def _ensure_cache(self):
        if self.router_obj:
            return
        self.router_obj = self.quantum.get_router_detail(self.router_id)

    def _verify_interfaces(self, logical_config, interfaces):
        router_macs = set((iface['lladdr'] for iface in interfaces))
        self.log.debug('MACs found: %s', ', '.join(sorted(router_macs)))

        expected_macs = set(p.mac_address
                            for p in logical_config.internal_ports)
        expected_macs.add(logical_config.management_port.mac_address)
        expected_macs.add(logical_config.external_port.mac_address)
        self.log.debug('MACs expected: %s', ', '.join(sorted(expected_macs)))

        return router_macs == expected_macs

    def _ensure_provider_ports(self, router):
        if router.management_port is None:
            self.log.info('Adding management port to router')
            mgt_port = self.quantum.create_router_management_port(router.id)
            router.management_port = mgt_port

        if router.external_port is None:
            self.log.info('Adding external port to router')
            ext_port = self.quantum.create_router_external_port(router)
            router.external_port = ext_port
        return router


def _get_management_address(router):
    network = netaddr.IPNetwork(cfg.CONF.management_prefix)

    tokens = ['%02x' % int(t, 16)
              for t in router.management_port.mac_address.split(':')]
    eui64 = int(''.join(tokens[0:3] + ['ff', 'fe'] + tokens[3:6]), 16)

    # the bit inversion is required by the RFC
    return str(netaddr.IPAddress(network.value + (eui64 ^ 0x0200000000000000)))
