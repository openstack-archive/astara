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

from novaclient.v1_1 import client
from novaclient import exceptions as novaclient_exceptions

from oslo_config import cfg
from oslo_log import log as logging


LOG = logging.getLogger(__name__)

OPTIONS = [
    cfg.StrOpt(
        'ssh_public_key',
        help="Path to the SSH public key for the 'akanda' user within "
             "router appliance instances",
        default='/etc/akanda-rug/akanda.pub')
]
cfg.CONF.register_opts(OPTIONS)


class InstanceInfo(object):
    def __init__(self, instance_id, name, management_port=None, ports=(),
                 image_uuid=None, booting=False, last_boot=None):
        self.id_ = instance_id
        self.name = name
        self.image_uuid = image_uuid
        self.booting = booting
        self.last_boot = datetime.utcnow() if booting else last_boot

        self.instance_up = True
        self.boot_duration = None
        self.nova_status = None

        self.management_port = management_port
        self._ports = ports

    @property
    def management_address(self):
        return str(self.management_port.fixed_ips[0].ip_address)

    @property
    def time_since_boot(self):
        if self.last_boot:
            return datetime.utcnow() - self.last_boot

    @property
    def ports(self):
        return self._ports

    @ports.setter
    def ports(self, port_list):
        self._ports = [p for p in port_list if p != self.management_port]

    def confirm_up(self):
        if self.booting:
            self.booting = False
            if self.last_boot:
                self.boot_duration = (datetime.utcnow() - self.last_boot)


class Nova(object):
    def __init__(self, conf):
        self.conf = conf
        self.client = client.Client(
            conf.admin_user,
            conf.admin_password,
            conf.admin_tenant_name,
            auth_url=conf.auth_url,
            auth_system=conf.auth_strategy,
            region_name=conf.auth_region)

    def create_instance(self, id, image_uuid, make_ports_callback):
        mgt_port, instance_ports = make_ports_callback()

        nics = [{'net-id': p.network_id, 'v4-fixed-ip': '', 'port-id': p.id}
                for p in ([mgt_port] + instance_ports)]

        LOG.debug('creating instance %s with image %s',
                  id, image_uuid)
        name = 'ak-' + id

        server = self.client.servers.create(
            name,
            image=image_uuid,
            flavor=self.conf.router_instance_flavor,
            nics=nics,
            config_drive=True,
            userdata=_format_userdata(mgt_port)
        )

        instance_info = InstanceInfo(
            server.id,
            name,
            mgt_port,
            instance_ports,
            image_uuid,
            True
        )

        assert server and server.created

        instance_info.nova_status = server.status
        return instance_info

    def get_instance_info(self, instance_id):
        """Retrieves an InstanceInfo object for a given instance_id

        :param router_id: UUID of the router being queried

        :returns: an InstanceInfo object representing the router instance
        """
        instance = self.get_instance_for_obj(instance_id)

        if instance:
            return InstanceInfo(
                instance.id,
                instance.name,
                image_uuid=instance.image['id']
            )

    def get_instance_for_obj(self, instance_id):
        """Retreives a nova server for a given router_id, based on instance
        name.

        :param instance_id: UUID of the instance_id being queried

        :returns: a novaclient.v2.servers.Server object or None
        """
        instances = self.client.servers.list(
            search_opts=dict(name='ak-' + instance_id)
        )

        if instances:
            return instances[0]
        else:
            return None

    def get_instance_by_id(self, instance_id):
        """Retreives a nova server for a given instance_id.

        :param instance_id: Nova instance ID of instance being queried

        :returns: a novaclient.v2.servers.Server object
        """
        try:
            return self.client.servers.get(instance_id)
        except novaclient_exceptions.NotFound:
            return None

    def destroy_instance(self, instance_info):
        if instance_info:
            LOG.debug('deleting instance for router %s', instance_info.name)
            self.client.servers.delete(instance_info.id_)

    def boot_instance(self, prev_instance_info, router_id, router_image_uuid,
                      make_ports_callback):

        if not prev_instance_info:
            instance = self.get_instance_for_obj(router_id)
        else:
            instance = self.get_instance_by_id(prev_instance_info.id_)

        # check to make sure this instance isn't pre-existing
        if instance:
            if 'BUILD' in instance.status:
                if prev_instance_info:
                    # if we had previous instance, return the same instance
                    # with updated status
                    prev_instance_info.nova_status = instance.status
                    instance_info = prev_instance_info
                else:
                    instance_info = InstanceInfo(
                        instance.id,
                        instance.name,
                        image_uuid=instance.image['id']
                    )
                return instance_info
            self.client.servers.delete(instance.id)
            return None

        # it is now safe to attempt boot
        instance_info = self.create_instance(
            router_id,
            router_image_uuid,
            make_ports_callback
        )
        return instance_info

# TODO(mark): Convert this to dynamic yaml, proper network prefix and ssh-keys

TEMPLATE = """#cloud-config

cloud_config_modules:
  - emit_upstart
  - set_hostname
  - locale
  - set-passwords
  - timezone
  - disable-ec2-metadata
  - runcmd

output: {all: '| tee -a /var/log/cloud-init-output.log'}

debug:
  - verbose: true

bootcmd:
  - /usr/local/bin/akanda-configure-management %(mac_address)s %(ip_address)s/64

users:
  - name: akanda
    gecos: Akanda
    groups: users
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock-passwd: true
    ssh-authorized-keys:
      - %(ssh_public_key)s

final_message: "Akanda appliance is running"
"""  # noqa


def _ssh_key():
    key = cfg.CONF.ssh_public_key
    if not key:
        return ''
    try:
        with open(key) as out:
            return out.read()
    except IOError:
        LOG.warning('Could not load router ssh public key from %s' % key)
        return ''


def _format_userdata(mgt_port):
    ctxt = {
        'ssh_public_key': _ssh_key(),
        'mac_address': mgt_port.mac_address,
        'ip_address': mgt_port.fixed_ips[0].ip_address,
    }
    return TEMPLATE % ctxt
