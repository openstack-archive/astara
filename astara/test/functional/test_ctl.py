# Copyright (c) 2015 Akanda, Inc. All Rights Reserved.
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

import requests
import subprocess
import testtools
import time

from oslo_config import cfg

from astara.test.functional import base


UPDATE_TIMEOUT = 15

CONF = cfg.CONF


class AstaraCTLTestCase(base.AstaraFunctionalBase):
    """Shells out and tests the astara-ctl CLI"""
    @classmethod
    def setUpClass(cls):
        super(AstaraCTLTestCase, cls).setUpClass()
        cls.tenant = cls.get_tenant()
        cls.neutronclient = cls.tenant.clients.neutronclient
        cls.network, cls.router = cls.tenant.setup_networking()

    def setUp(self):
        super(AstaraCTLTestCase, self).setUp()
        self.assert_router_is_active(self.router['id'])
        # refresh router ref now that its active
        router = self.neutronclient.show_router(self.router['id'])
        self.resource_id = router['router']['id']

    def get_hostname(self):
        return self.ssh_client(self.resource_id).exec_command(
            'cat /etc/hostname').strip()

    def set_hostname(self, hostname):
        self.ssh_client(self.resource_id).exec_command(
            'echo %s | sudo tee /etc/hostname' % hostname
        )
        new_hostname = self.ssh_client(self.resource_id).exec_command(
            'cat /etc/hostname'
        ).strip()
        self.assertEqual(new_hostname, hostname)

    def assert_hostname(self, hostname):
        i = 0
        while i < UPDATE_TIMEOUT:
            updated_hostname = self.ssh_client(self.resource_id).exec_command(
                'cat /etc/hostname').strip()
            if updated_hostname == hostname:
                return
            i += 1
            time.sleep(1)
        raise self.failureException(
            'After %s sec. Appliance /etc/hostname contents != %s (actual: %s)'
            % (UPDATE_TIMEOUT, hostname, updated_hostname))

    def run_command(self, command, subcommand=None, resource_id=None):
        cmd = ['astara-ctl', command]
        if subcommand:
            cmd.append(subcommand)
        if resource_id:
            cmd.append(resource_id)
        print 'Running cmd: %s' % cmd
        subprocess.check_output(cmd)

    def _update(self, target):
        orig_hostname = self.get_hostname()
        self.set_hostname('foobar')
        self.run_command(
            command=target,
            subcommand='update',
            resource_id=self.resource_id,
        )
        self.assert_hostname(orig_hostname)

    def _rebuild(self, target):
        orig_server = self.get_router_appliance_server(
            resource='router',
            uuid=self.resource_id,
            wait_for_active=True,
        )
        self.ssh_client(self.resource_id).exec_command('sudo touch /etc/foo')
        self.run_command(
            command=target,
            subcommand='rebuild',
            resource_id=self.resource_id
        )
        time.sleep(10)
        new_server = self.get_router_appliance_server(
            resource='router',
            uuid=self.resource_id,
            wait_for_active=True,
        )
        self.assert_router_is_active(self.resource_id)
        self.assertNotEqual(
            orig_server.id,
            new_server.id,
        )
        check_flag_file = self.ssh_client(self.resource_id).exec_command(
            "ls /etc/foo || echo 'not found'").strip()
        self.assertEqual(
            check_flag_file,
            'not found',
        )

    def _debug_manage(self, target):
        # Overwrite config in a resource appliance, manage it,
        # issue an update and verify the that update is not acted
        # upon.  Then, manage it and verify it is.
        orig_hostname = self.get_hostname()
        new_hostname = 'foobar'
        self.set_hostname(new_hostname)
        self.assert_hostname(new_hostname)
        self.run_command(
            command=target,
            subcommand='debug',
            resource_id=self.resource_id
        )
        time.sleep(2)
        self.run_command(
            command=target,
            subcommand='update',
            resource_id=self.resource_id
        )
        for i in range(1, 5):
            self.assert_hostname(new_hostname)

        self.run_command(
            command=target,
            subcommand='manage',
            resource_id=self.resource_id
        )
        time.sleep(2)
        self.run_command(
            command=target,
            subcommand='update',
            resource_id=self.resource_id
        )
        self.assert_hostname(orig_hostname)

    def test_rebuild_resource(self):
        self._rebuild('resource')

    def test_update_resource(self):
        self._update('resource')

    def test_debug_manage_resource(self):
        self._debug_manage('resource')

    def test_rebuild_router(self):
        self._rebuild('router')

    def test_update_router(self):
        self._update('router')

    def test_debug_manage_router(self):
        self._debug_manage('router')

    def test_poll(self):
        self.run_command(
            command='poll',
        )


API_PATHS = {
    'poll': '/poll',
    'router': '/router',
}


class AstaraAPITestCase(AstaraCTLTestCase):
    """Calls the astara-orchestrator API to test CTL commands issued there"""
    def setUp(self):
        super(AstaraAPITestCase, self).setUp()
        ksc = self.admin_clients.keystoneclient
        self.mgt_url = ksc.service_catalog.url_for(service_type='astara')

    def make_url(self, command, subcommand=None, resource_id=None):
        url = self.mgt_url + API_PATHS[command]
        if not subcommand and not resource_id:
            return url
        url = url + '/%s/%s' % (subcommand, resource_id)
        return url

    def run_command(self, command, subcommand=None, resource_id=None):
        url = self.make_url(command, subcommand, resource_id)
        self.assertTrue(
            requests.put(url).ok, msg='request to API failed: %s' % url)

    @testtools.skip('API does not yet support /resource')
    def test_rebuild_resource(self):
        pass

    @testtools.skip('API does not yet support /resource')
    def test_update_resource(self):
        pass

    @testtools.skip('API does not yet support /resource')
    def test_debug_manage_resource(self):
        pass
