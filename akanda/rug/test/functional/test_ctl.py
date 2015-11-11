
import subprocess
import time

from akanda.rug.test.functional import base


UPDATE_TIMEOUT = 15


class AstaraCTLTestBase(base.AkandaFunctionalBase):
    def setUp(self):
        super(AstaraCTLTestBase, self).setUp()
        self.resource_id = self.config['akanda_test_router_uuid']

    def run_command(self, command, subcommand, resource_id, **kwargs):
        print 'running command: %s for %s /w %s' % (
            command, resource_id, kwargs
        )
        cmd = ['astara-ctl', command, subcommand, resource_id]
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
        while  i < UPDATE_TIMEOUT:
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

    def test_rebuild_resource(self):
        self._rebuild('resource')
