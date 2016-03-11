#!/bin/bash -x
echo $LOGDIR
FUNC_TEST_DIR=$(dirname $0)/../astara/test/functional/
CONFIG_FILE=$FUNC_TEST_DIR/test.conf
LOGDIR=${LOGDIR:-$FUNC_TEST_DIR}
LOG_FILE=$LOGDIR/astara_functional.log
APPLIANCE_API_PORT=${APPLIANCE_API_PORT:-5000}
SERVICE_TENANT_NAME=${SERVICE_TENANT_NAME:-service}
if [ -z "$SERVICE_TENANT_ID" ]; then
    SERVICE_TENANT_ID="$(openstack project list | grep $SERVICE_TENANT_NAME | awk '{ print $2 }')"
    if [ -z "$SERVICE_TENANT_ID" ]; then
        # Fallback to V2
        SERVICE_TENANT_ID="$(keystone tenant-list | grep $SERVICE_TENANT_NAME | awk '{ print $2 }')"
    fi
fi

cat <<END >$CONFIG_FILE
[DEFAULT]
debug=True
use_stderr=False
use_syslog=False
os_auth_url=$OS_AUTH_URL
os_username=$OS_USERNAME
os_password=$OS_PASSWORD
os_tenant_name=$OS_TENANT_NAME
service_tenant_name=$SERVICE_TENANT_NAME
service_tenant_id=$SERVICE_TENANT_ID
appliance_api_port=$APPLIANCE_API_PORT
astara_auto_add_resources=False

# Defaults for the gate
health_check_timeout=10
appliance_active_timeout=480
log_file=/opt/stack/logs/astara_functional.log
END

tox -e  functional
./tools/debug.sh
