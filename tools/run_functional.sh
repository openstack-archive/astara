#!/bin/bash -xe

FUNC_TEST_DIR=$(dirname $0)/../akanda/rug/test/functional/
CONFIG_FILE=$FUNC_TEST_DIR/test.conf

APPLIANCE_API_PORT=${APPLIANCE_API_PORT:-5000}
SERVICE_TENANT_NAME=${SERVICE_TENANT_NAME:-service}
if [ -z "$SERVICE_TENANT_ID" ]; then
    SERVICE_TENANT_ID="$(keystone tenant-list | grep $SERVICE_TENANT_NAME | awk '{ print $2 }')"
fi

cat <<END >$CONFIG_FILE
[functional]
os_auth_url=$OS_AUTH_URL
os_username=$OS_USERNAME
os_password=$OS_PASSWORD
os_tenant_name=$OS_TENANT_NAME
service_tenant_name=$SERVICE_TENANT_NAME
service_tenant_id=$SERVICE_TENANT_ID
appliance_api_port=$APPLIANCE_API_PORT
END

sudo -E tox -e  functional
