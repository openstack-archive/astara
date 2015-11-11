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

import netaddr
import requests
import subprocess
import testtools

import time
from akanda.rug.test.functional import base


UPDATE_TIMEOUT = 15


class AstaraCTLTestCase(base.AkandaFunctionalBase):
    """Shells out and tests the astara-ctl CLI"""
    def setUp(self):
        super(AstaraCTLTestCase, self).setUp()
        self.resource_id = self.config['akanda_test_router_uuid']

    def run_command(self, command, subcommand=None, resource_id=None):
        cmd = ['astara-ctl', command]
        if subcommand:
            cmd.append(subcommand)
        if resource_id:
            cmd.append(resource_id)
        print 'Running cmd: %s' % cmd
        subprocess.check_output(cmd)

    def _update(self, target):
        orig_hostname = self.ssh_client(self.resource_id).exec_command(
            'cat /etc/hostname').strip()
        self.ssh_client(self.resource_id).exec_command(
            'echo foobar | sudo tee /etc/hostname'
        )
        new_hostname = self.ssh_client(self.resource_id).exec_command(
            'cat /etc/hostname'
        ).strip()
        self.assertEqual(new_hostname, 'foobar')

        self.run_command(
            command=target,
            subcommand='update',
            resource_id=self.resource_id,
        )

        i = 0
        while i < UPDATE_TIMEOUT:
            updated_hostname = self.ssh_client(self.resource_id).exec_command(
                'cat /etc/hostname').strip()
            if updated_hostname == orig_hostname:
                return
            i += 1
            time.sleep(1)

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

    def test_rebuild_resource(self):
        self._rebuild('resource')

    def test_update_resource(self):
        self._update('resource')

    def test_rebuild_router(self):
        self._rebuild('router')

    def test_update_router(self):
        self._update('router')

    def test_poll(self):
        self.run_command(
            command ='poll',
        )

def get_local_service_ip(management_prefix):
    mgt_net = netaddr.IPNetwork(management_prefix)
    rug_ip = '%s/%s' % (netaddr.IPAddress(mgt_net.first + 1),
                        mgt_net.prefixlen)
    return rug_ip

API_PATHS = {
    'poll': '/poll',
    'router': '/router',
}


class AstaraAPITestCase(AstaraCTLTestCase):
    """Calls the astara-orchestrator API to test CTL commands issued there"""
    def setUp(self):
        super(AstaraAPITestCase, self).setUp()
        management_addr = get_local_service_ip(
            self.config['management_prefix']
        ).split('/')[0]
        if ':' in management_addr:
            management_addr = '[%s]' % management_addr
        self.mgt_url = 'http://%s:%s' % (
            management_addr, self.config['management_port'])

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
        return

    @testtools.skip('API does not yet support /resource')
    def test_update_resource(self):
        return


