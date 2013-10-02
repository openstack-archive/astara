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
BOOT_WAIT = 60
RETRY_DELAY = 1


class VmManager(object):
    def __init__(self, router_id, log):
        self.router_id = router_id
        self.log = log
        self.state = DOWN
        self._logical_router = None

        self.quantum = quantum.Quantum(cfg.CONF)

    def update_state(self, silent=False):
        self._ensure_cache()

        addr = _get_management_address(router)
        for i in xrange(MAX_RETRIES):
            try:
                if router_api.is_alive(addr, cfg.CONF.akanda_mgt_service_port):
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

        if self.state == DOWN:
            self.state = UP

        return self.state

    def boot(self):
        self._logical_router = self.quantum.get_router_detail(router_id)

        self.log.info('Booting router')
        nova_client = nova.Nova(cfg.CONF)
        nova_client.reboot_router_instance(self._logical_router)
        self.state = DOWN

        start = time.time()
        while time.time() - start < BOOT_WAIT:
            if self.update_state(silent=True) in (UP, CONFIGURED):
                return
            self.log.debug('Router has not finished booting. IP: %s', addr)

        self.log.error('Router failed to boot within %d secs', BOOT_WAIT)

    def stop(self):
        self._ensure_cache()
        self.log.info('Destroying router')

        nova_client = nova.Nova(cfg.CONF)
        nova_client.reboot_router_instance(self._logical_router)

    def configure(self):
        self.log.debug('Begin router config')
        self.state = UP

        self._logical_router = self.quantum.get_router_detail(router_id)

        addr = _get_management_address(self._logical_router)

        interfaces = router_api.get_interfaces(
            addr,
            cfg.CONF.akanda_mgt_service_port
        )

        if not self._verify_interfaces(self._logical_router, interfaces):
            self.state = RESTART
            return

        config = configuration.build_config(
            self.quantum,
            self._logical_router,
            interfaces
        )

        for i in xrange(MAX_RETRIES):
            try:
                router_api.update_config(
                    addr,
                    cfg.CONF.akanda_mgt_service_port,
                    config
                )
            except Exception as e:
                self.log.exception('failed to update config')
                time.sleep(i + 1)
            else:
                self.state = CONFIGURED
                self.log.debug('Router config updated')
                return

    def _ensure_cache(self):
        if self._logical_router:
            return
        self._logical_router = self.quantum.get_router_detail(router_id)

    def _verify_interfaces(self, logical_config, interfaces):
        router_macs = set((iface['lladdr'] for iface in interfaces))
        self.log.debug('MACs found: %s', ', '.join(sorted(router_macs)))

        expected_macs = set((p.mac_address for p in router.internal_ports))
        expected_macs.add(router.management_port.mac_address)
        expected_macs.add(router.external_port.mac_address)
        self.log.debug('MACs expected: %s', ', '.join(sorted(expected_macs)))

        return router_macs == expected_macs


def _get_management_address(router):
    network = netaddr.IPNetwork(cfg.CONF.management_prefix)

    tokens = ['%02x' % int(t, 16)
              for t in router.management_port.mac_address.split(':')]
    eui64 = int(''.join(tokens[0:3] + ['ff', 'fe'] + tokens[3:6]), 16)

    # the bit inversion is required by the RFC
    return str(netaddr.IPAddress(network.value + (eui64 ^ 0x0200000000000000)))
