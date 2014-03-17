"""Constants for the commands
"""

# Dump debugging details about the worker processes and threads
WORKERS_DEBUG = 'workers-debug'

# Put a router in debug/manage mode
# Expects a 'router_id' argument in the payload with the UUID of the router
ROUTER_DEBUG = 'router-debug'
ROUTER_MANAGE = 'router-manage'

# Put a tenant in debug/manage mode
# Expects a 'tenant_id' argument in the payload with the UUID of the tenant
TENANT_DEBUG = 'tenant-debug'
TENANT_MANAGE = 'tenant-manage'

# Configuration commands
CONFIG_RELOAD = 'config-reload'
