# Copyright (c) 2016 Akanda, Inc. All Rights Reserved.
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


import itertools
from oslo_config import cfg


functional_test_opts = [
    cfg.StrOpt(
        'os_auth_url', required=True,
        help='Keystone auth URL'),
    cfg.StrOpt(
        'os_username', required=True,
        help='Username of admin user'),
    cfg.StrOpt(
        'os_password', required=True,
        help='Password of admin user'),
    cfg.StrOpt(
        'os_tenant_name', required=True,
        help='Tenant name of admin user'),
    cfg.StrOpt(
        'service_tenant_id', required=True,
        help='Tenant ID for the astara service user'),
    cfg.StrOpt(
        'service_tenant_name', required=True,
        help='Tenant name of the astara service user'),
    cfg.StrOpt(
        'appliance_api_port', required=True,
        help='The port on which appliance API servers listen'),
    cfg.BoolOpt(
        'astara_auto_add_resources', required=False, default=True,
        help='Whether astara-neutron is configured to auto-add resources'),
    cfg.IntOpt(
        'appliance_active_timeout', required=False, default=340,
        help='Timeout (sec) for an appliance to become ACTIVE'),
    cfg.StrOpt(
        'test_subnet_cidr', required=False, default='10.1.1.0/24'),
    cfg.IntOpt(
        'health_check_period', required=False, default=60,
        help='Time health_check_period astara-orchestrator is configured to '
             'use')
]


def list_opts():
    return [
        ('functional',
         itertools.chain(functional_test_opts))]


def register_opts():
    cfg.CONF.register_opts(functional_test_opts)
