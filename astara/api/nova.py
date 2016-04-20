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

import netaddr
from novaclient import client
from novaclient import exceptions as novaclient_exceptions
from oslo_config import cfg
from oslo_log import log as logging

from astara.common.i18n import _LW, _LE, _LI
from astara.api import keystone
from astara.api import neutron
from astara.common import config
from astara.pez import rpcapi as pez_api

LOG = logging.getLogger(__name__)

OPTIONS = [
    cfg.StrOpt(
        'ssh_public_key',
        help="Path to the SSH public key for the 'astara' user within "
             "appliance instances",
        default='/etc/astara/astara.pub'),
    cfg.StrOpt(
        'instance_provider', default='on_demand',
        help='Which instance provider to use (on_demand, pez)'),
    cfg.StrOpt(
        'astara_boot_command', default='astara-configure-management',
        help='The boot command to run to configure the appliance'),
]
cfg.CONF.register_opts(OPTIONS)


class NovaInstanceDeleteTimeout(Exception):
    pass


class InstanceInfo(object):
    def __init__(self, instance_id, name, management_port=None, ports=(),
                 image_uuid=None, status=None, last_boot=None):
        self.id_ = instance_id
        self.name = name
        self.image_uuid = image_uuid

        self.nova_status = status

        self.management_port = management_port
        self._ports = ports
        self.last_boot = last_boot

    @property
    def booting(self):
        return 'BUILD' in self.nova_status

    @property
    def management_address(self):
        if self.management_port:
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

    @classmethod
    def from_nova(cls, instance):
        """
        Returns an instantiated InstanceInfo object with data gathered from
        an existing Nova server.

        :param instance: novaclient.v2.servers.Server object for an existing
                         nova instance.
        :returns: InstanceInfo instance
        """
        # NOTE(adam_g): We do not yet actually rebuild any instances.
        #               A rug REBUILD is actually a delete/create, so it
        #               should be safe to track last_boot as the timestamp
        #               the instance was last booted.
        last_boot = datetime.strptime(
            instance.created, "%Y-%m-%dT%H:%M:%SZ")
        return cls(
            instance_id=instance.id,
            name=instance.name,
            image_uuid=instance.image['id'],
            status=instance.status,
            last_boot=last_boot,
        )


class InstanceProvider(object):
    def __init__(self, client):
        self.nova_client = client
        LOG.debug(_LI(
            'Initialized %s with novaclient %s'),
            self.__class__.__name__, self.nova_client)

    def create_instance(self, driver, name, image_uuid, flavor,
                        make_ports_callback):
        """Create or get an instance

        :param router_id: UUID of the resource that the instance will host

        :returns: InstanceInfo object with at least id, name and image_uuid
                  set.
        """


class PezInstanceProvider(InstanceProvider):
    def __init__(self, client):
        super(PezInstanceProvider, self).__init__(client)
        self.rpc_client = pez_api.AstaraPezAPI(rpc_topic='astara-pez')
        LOG.debug(_LI(
            'Initialized %s with rpc client %s'),
            self.__class__.__name__, self.rpc_client)

    def create_instance(self, resource_type, name, image_uuid, flavor,
                        make_ports_callback):
        # TODO(adam_g): pez already creates the mgt port on boot and the one
        # we create here is wasted. callback needs to be adjusted
        mgt_port, instance_ports = make_ports_callback()

        mgt_port_dict = {
            'id': mgt_port.id,
            'network_id': mgt_port.network_id,
        }
        instance_ports_dicts = [{
            'id': p.id, 'network_id': p.network_id,
        } for p in instance_ports]

        LOG.debug('Requesting new %s instance from Pez.', resource_type)
        pez_instance = self.rpc_client.get_instance(
            resource_type, name, mgt_port_dict, instance_ports_dicts)
        LOG.debug('Got %s instance %s from Pez.',
                  resource_type, pez_instance['id'])

        server = self.nova_client.servers.get(pez_instance['id'])

        # deserialize port data
        mgt_port = neutron.Port.from_dict(pez_instance['management_port'])
        instance_ports = [
            neutron.Port.from_dict(p)
            for p in pez_instance['instance_ports']]

        boot_time = datetime.strptime(
            server.created, "%Y-%m-%dT%H:%M:%SZ")
        instance_info = InstanceInfo(
            instance_id=server.id,
            name=server.name,
            management_port=mgt_port,
            ports=instance_ports,
            image_uuid=image_uuid,
            status=server.status,
            last_boot=boot_time)

        return instance_info


class OnDemandInstanceProvider(InstanceProvider):
    def create_instance(self, resource_type, name, image_uuid, flavor,
                        make_ports_callback):
        mgt_port, instance_ports = make_ports_callback()

        nics = [{'net-id': p.network_id,
                 'v4-fixed-ip': '',
                 'port-id': p.id}
                for p in ([mgt_port] + instance_ports)]

        LOG.debug('creating instance %s with image %s',
                  name, image_uuid)

        server = self.nova_client.servers.create(
            name,
            image=image_uuid,
            flavor=flavor,
            nics=nics,
            config_drive=True,
            userdata=format_userdata(mgt_port)
        )

        server_status = None
        for i in range(1, 10):
            try:
                # novaclient loads attributes lazily and we need to wait until
                # the client object is populated.  moving to keystone sessions
                # exposes this race.
                server_status = server.status
            except AttributeError:
                time.sleep(.5)
        assert server_status

        boot_time = datetime.strptime(
            server.created, "%Y-%m-%dT%H:%M:%SZ")
        instance_info = InstanceInfo(
            instance_id=server.id,
            name=name,
            management_port=mgt_port,
            ports=instance_ports,
            image_uuid=image_uuid,
            status=server.status,
            last_boot=boot_time)

        return instance_info

INSTANCE_PROVIDERS = {
    'on_demand': OnDemandInstanceProvider,
    'pez': PezInstanceProvider,
    'default': OnDemandInstanceProvider,
}


def get_instance_provider(provider):
    try:
        return INSTANCE_PROVIDERS[provider]
    except KeyError:
        default = INSTANCE_PROVIDERS['default']
        LOG.error(_LE('Could not find %s instance provider, using default %s'),
                  provider, default)
        return default


class Nova(object):
    def __init__(self, conf):
        self.conf = conf
        ks_session = keystone.KeystoneSession()
        self.client = client.Client(
            version='2',
            session=ks_session.session,
            region_name=conf.auth_region,
            endpoint_type=conf.endpoint_type)

        try:
            self.instance_provider = get_instance_provider(
                conf.instance_provider)(self.client)
        except AttributeError:
            default = INSTANCE_PROVIDERS['default']
            LOG.error(_LE('Could not find provider config, using default %s'),
                      default)
            self.instance_provider = default(self.client)

    def get_instances_for_obj(self, name):
        """Retrieves all nova servers for a given instance name.

        :param name: name of the instance being queried

        :returns: a list of novaclient.v2.servers.Server objects or []
        """
        search_opt = '^' + name + '.*$'
        instances = self.client.servers.list(
            search_opts=dict(name=search_opt)
        )
        if not instances:
            return []
        return [InstanceInfo.from_nova(i) for i in instances]

    def get_instance_for_obj(self, name):
        """Retrieves a nova server for a given instance name.

        :param name: name of the instance being queried

        :returns: a novaclient.v2.servers.Server object or None
        """
        instances = self.client.servers.list(
            search_opts=dict(name=name)
        )

        if instances:
            return instances[0]
        else:
            return None

    def get_instance_by_id(self, instance_id):
        """Retrieves a nova server for a given instance_id.

        :param instance_id: Nova instance ID of instance being queried

        :returns: a novaclient.v2.servers.Server object
        """
        try:
            return self.client.servers.get(instance_id)
        except novaclient_exceptions.NotFound:
            return None

    def destroy_instance(self, instance_info):
        if instance_info:
            LOG.debug('deleting instance %s', instance_info.name)
            self.client.servers.delete(instance_info.id_)

    def boot_instance(self,
                      resource_type,
                      prev_instance_info,
                      name,
                      image_uuid,
                      flavor,
                      make_ports_callback):

        if not prev_instance_info:
            instance = self.get_instance_for_obj(name)
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
                    instance_info = InstanceInfo.from_nova(instance)
                return instance_info

            self.client.servers.delete(instance.id)
            return None

        # it is now safe to attempt boot
        instance_info = self.instance_provider.create_instance(
            resource_type=resource_type,
            name=name,
            image_uuid=image_uuid,
            flavor=flavor,
            make_ports_callback=make_ports_callback
        )
        return instance_info

    def update_instance_info(self, instance_info):
        """Used primarily for updating tracked instance status"""
        instance = self.get_instance_by_id(instance_info.id_)
        if not instance:
            return None
        instance_info.nova_status = instance.status
        return instance_info

    def delete_instances_and_wait(self, instance_infos):
        """Deletes the nova instance and waits for its deletion to complete"""
        to_poll = list(instance_infos)

        for inst in instance_infos:
            try:
                self.destroy_instance(inst)
            except novaclient_exceptions.NotFound:
                pass
            except Exception:
                LOG.exception(
                    _LE('Error deleting instance %s' % inst.id_))
                to_poll.remove(inst)

        # XXX parallelize this
        timed_out = []
        for inst in to_poll:
            start = time.time()
            i = 0
            while time.time() - start < cfg.CONF.boot_timeout:
                i += 1
                if not self.get_instance_by_id(inst.id_):
                    LOG.debug('Instance %s has been deleted', inst.id_)
                    break
                LOG.debug(
                    'Instance %s has not finished stopping', inst.id_)
                time.sleep(cfg.CONF.retry_delay)
            else:
                timed_out.append(inst)
                LOG.error(_LE(
                    'Instance %s failed to stop within %d secs'),
                    inst.id_, cfg.CONF.boot_timeout)

        if timed_out:
            raise NovaInstanceDeleteTimeout()


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
  - /usr/local/bin/%(boot_command)s %(mac_address)s %(ip_address)s/%(prefix)d

users:
  - name: astara
    gecos: Astara
    groups: users
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock-passwd: true
    ssh-authorized-keys:
      - %(ssh_public_key)s

final_message: "Astara appliance is running"
"""  # noqa


def _ssh_key():
    key = config.get_best_config_path(cfg.CONF.ssh_public_key)
    if not key:
        return ''
    try:
        with open(key) as out:
            return out.read()
    except IOError:
        LOG.warning(_LW('Could not load router ssh public key from %s'), key)
        return ''


def format_userdata(mgt_port):
    mgt_net = netaddr.IPNetwork(cfg.CONF.management_prefix)
    ctxt = {
        'ssh_public_key': _ssh_key(),
        'mac_address': mgt_port.mac_address,
        'ip_address': mgt_port.fixed_ips[0].ip_address,
        'boot_command': cfg.CONF.astara_boot_command,
        'prefix': mgt_net.prefixlen
    }
    out = TEMPLATE % ctxt
    LOG.debug('Rendered cloud-init for instance: %s' % out)
    return out
