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


"""Constants for the commands
"""

# Special values for dispatching
WILDCARDS = ('*', 'error')

# Dump debugging details about the worker processes and threads
WORKERS_DEBUG = 'workers-debug'

# Router commands expect a 'router_id' argument in the payload with
# the UUID of the router

# Put a router in debug/manage mode
ROUTER_DEBUG = 'router-debug'
ROUTER_MANAGE = 'router-manage'
# Send an updated config to the router whether it is needed or not
ROUTER_UPDATE = 'router-update'
# Rebuild a router from scratch
ROUTER_REBUILD = 'router-rebuild'

# Put a tenant in debug/manage mode
# Expects a 'tenant_id' argument in the payload with the UUID of the tenant
TENANT_DEBUG = 'tenant-debug'
TENANT_MANAGE = 'tenant-manage'

# Configuration commands
CONFIG_RELOAD = 'config-reload'

# Force a poll of all routers right now
POLL = 'poll'
