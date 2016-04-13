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


import mock

from astara.api.config import loadbalancer as lb_config
from astara.test.unit import base, fakes


class TestLoadbalancerConfigAPI(base.RugTestBase):
    @mock.patch('astara.api.config.common.network_config')
    def test_build_config(self, fake_network_config):
        fake_client = mock.Mock()
        fake_lb = fakes.fake_loadbalancer()
        fake_lb_net = mock.Mock()
        fake_mgt_net = mock.Mock()
        fake_mgt_port = mock.Mock(
            network_id='fake_mgt_network_id',
        )
        fake_iface_map = {
            fake_lb.vip_port.network_id: fake_lb_net,
            fake_mgt_port.network_id: fake_mgt_net,
        }
        fake_network_config.side_effect = [
            'fake_lb_net_dict', 'fake_mgt_net_dict'
        ]
        res = lb_config.build_config(
            fake_client, fake_lb, fake_mgt_port, fake_iface_map)
        exp_lb_dict = fake_lb.to_dict()
        exp_lb_dict['networks'] = ['fake_lb_net_dict', 'fake_mgt_net_dict']
        expected = {
            'hostname': 'ak-loadbalancer-%s' % fake_lb.tenant_id,
            'tenant_id': fake_lb.tenant_id,
            'networks': ['fake_lb_net_dict', 'fake_mgt_net_dict'],
            'services': {
                'loadbalancer': exp_lb_dict,
            }
        }
        self.assertEqual(res, expected)
