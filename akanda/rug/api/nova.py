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

import logging

from novaclient.v1_1 import client


LOG = logging.getLogger(__name__)


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

    def create_router_instance(self, router, router_image_uuid):
        nics = [{'net-id': p.network_id, 'v4-fixed-ip': '', 'port-id': p.id}
                for p in router.ports]

        # Sometimes a timing problem makes Nova try to create an akanda
        # instance using some ports that haven't been cleaned up yet from
        # Neutron. This problem makes the novaclient return an Internal Server
        # Error to the rug.
        # We can safely ignore this exception because the failed task is going
        # to be requeued and executed again later when the ports should be
        # finally cleaned up.
        LOG.debug('creating vm for router %s with image %s',
                  router.id, router_image_uuid)
        server = self.client.servers.create(
            'ak-' + router.id,
            image=router_image_uuid,
            flavor=self.conf.router_instance_flavor,
            nics=nics)
        assert server and server.created

    def get_instance(self, router):
        instances = self.client.servers.list(
            search_opts=dict(name='ak-' + router.id))

        if instances:
            return instances[0]
        else:
            return None

    def get_router_instance_status(self, router):
        instance = self.get_instance(router)
        if instance:
            return instance.status
        else:
            return None

    def destroy_router_instance(self, router):
        instance = self.get_instance(router)
        if instance:
            LOG.debug('deleting vm for router %s', router.id)
            self.client.servers.delete(instance.id)

    def reboot_router_instance(self, router, router_image_uuid):
        instance = self.get_instance(router)
        if instance:
            if 'BUILD' in instance.status:
                return True

            self.client.servers.delete(instance.id)
            return False
        self.create_router_instance(router, router_image_uuid)
        return True
