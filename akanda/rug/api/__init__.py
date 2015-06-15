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

from oslo_config import cfg

CONF = cfg.CONF


api_opts = [
    cfg.StrOpt('admin_user'),
    cfg.StrOpt('admin_password', secret=True),
    cfg.StrOpt('admin_tenant_name'),
    cfg.StrOpt('auth_url'),
    cfg.StrOpt('auth_strategy', default='keystone'),
    cfg.StrOpt('auth_region'),
    cfg.IntOpt('max_retries', default=3),
    cfg.IntOpt('retry_delay', default=1),
]
CONF.register_opts(api_opts)
