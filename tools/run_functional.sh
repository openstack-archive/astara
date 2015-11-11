#!/bin/bash -xe

FUNC_TEST_DIR=$(dirname $0)/../akanda/rug/test/functional/
CONFIG_FILE=$FUNC_TEST_DIR/test.conf
ASTARA_CONFIG=${ASTARA_CONFIG_FILE:-/etc/astara/orchestrator.ini}

APPLIANCE_API_PORT=${APPLIANCE_API_PORT:-5000}
SERVICE_TENANT_NAME=${SERVICE_TENANT_NAME:-service}
if [ -z "$SERVICE_TENANT_ID" ]; then
    SERVICE_TENANT_ID="$(keystone tenant-list | grep $SERVICE_TENANT_NAME | awk '{ print $2 }')"
fi

# Functional tests require a test akanda router be created prior to the test
# run. Devstack does this, but you may specify another here.  If not specified,
# the ID of the devstack created router will be used.
AKANDA_TEST_ROUTER_UUID=${AKANDA_TEST_ROUTER_UUID:-''}

function find_router() {
    # Find the UUID of the akanda router created by devstack.
    router=$(neutron router-list | grep "ak-" | awk '{ print $2 }')
    if [ $(echo "$router" | wc -l) -gt 1 ]; then
        echo "ERROR: Found multiple akanda routers, cannot continue."
        exit 1
    elif [ -z "$router" ]; then
        echo "ERROR: Could not locate akanda router."
        exit 1
    fi
    echo $router
}

function get_from_config() {
    if [ ! -f $ASTARA_CONFIG ]; then
        echo "ERROR: Could not locate astara-orchestrator config @ $ASTARA_CONFIG"
        exit 1
    fi
    val=$(cat $ASTARA_CONFIG | grep "^$1" | cut -d= -f2)
    if [ -z "$val" ]; then
        echo "ERROR: Could not get value for $1 in $ASTARA_CONFIG"
        exit 1
    fi
    echo "$val"
}
cat <<END >$CONFIG_FILE
[functional]
appliance_active_timeout=480
os_auth_url=$OS_AUTH_URL
os_username=$OS_USERNAME
os_password=$OS_PASSWORD
os_tenant_name=$OS_TENANT_NAME
service_tenant_name=$SERVICE_TENANT_NAME
service_tenant_id=$SERVICE_TENANT_ID
appliance_api_port=$APPLIANCE_API_PORT
END

if [ -z "$AKANDA_TEST_ROUTER_UUID" ]; then
    AKANDA_TEST_ROUTER_UUID="$(find_router)"
fi
echo "akanda_test_router_uuid=$AKANDA_TEST_ROUTER_UUID" >>$CONFIG_FILE

if [ -z "$ASTARA_MANAGEMENT_PREFIX" ]; then
    AKANDA_MANAGEMENT_PREFIX="$(get_from_config management_prefix)"
fi

if [ -z "$ASTARA_MANAGEMENT_PORT" ]; then
    AKANDA_MANAGEMENT_PORT="$(get_from_config rug_api_port)"
fi
cat <<END >>$CONFIG_FILE
management_prefix=$AKANDA_MANAGEMENT_PREFIX
management_port=$AKANDA_MANAGEMENT_PORT
END

tox -e  functional
