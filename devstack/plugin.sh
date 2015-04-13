# -*- mode: shell-script -*-

# Set up default directories
AKANDA_NEUTRON_DIR=$DEST/akanda-quantum
AKANDA_NEUTRON_REPO=${AKANDA_NEUTRON_REPO:-git@github.com:neutron/akanda-neutron.git}
AKANDA_NEUTRON_BRANCH=${AKANDA_NEUTRON_BRANCH:-master}

AKANDA_DEV_APPLIANCE=${AKANDA_DEV_APPLIANCE:-http://markmcclain.objects.dreamhost.com/akanda.qcow2}

AKANDA_CONF_DIR=/etc/akanda-rug
AKANDA_RUG_CONF=$AKANDA_CONF_DIR/rug.ini

ROUTER_INSTANCE_FLAVOR=2
PUBLIC_INTERFACE_DEFAULT='eth0'

function configure_akanda() {
    if [[ ! -d $AKANDA_CONF_DIR ]]; then
        sudo mkdir -p $AKANDA_CONF_DIR
    fi
    sudo chown $STACK_USER $AKANDA_CONF_DIR

    cp $AKANDA_RUG_DIR/etc/rug.ini $AKANDA_RUG_CONF
    iniset $AKANDA_RUG_CONF DEFAULT verbose True
    iniset $AKANDA_RUG_CONF DEFAULT admin_user $Q_ADMIN_USERNAME
    iniset $AKANDA_RUG_CONF DEFAULT admin_password $SERVICE_PASSWORD
    iniset $AKANDA_RUG_CONF DEFAULT rabbit_userid $RABBIT_USERID
    iniset $AKANDA_RUG_CONF DEFAULT rabbit_host $RABBIT_HOST
    iniset $AKANDA_RUG_CONF DEFAULT rabbit_password $RABBIT_PASSWORD
    iniset $AKANDA_RUG_CONF DEFAULT amqp_url "amqp://$RABBIT_USERID:$RABBIT_PASSWORD@$RABBIT_HOST:$RABBIT_PORT/"
    iniset $AKANDA_RUG_CONF DEFAULT control_exchange "neutron"
    iniset $AKANDA_RUG_CONF DEFAULT router_instance_flavor $ROUTER_INSTANCE_FLAVOR
    iniset $AKANDA_RUG_CONF DEFAULT boot_timeout "6000"
    iniset $AKANDA_RUG_CONF DEFAULT num_worker_processes "2"
    iniset $AKANDA_RUG_CONF DEFAULT num_worker_threads "2"
    iniset $AKANDA_RUG_CONF DEFAULT reboot_error_threshold "2"
}

function configure_akanda_nova() {
    iniset $NOVA_CONF DEFAULT service_neutron_metadata_proxy True
}

function configure_akanda_neutron() {
    iniset $NEUTRON_CONF DEFAULT core_plugin akanda.neutron.plugins.ml2_neutron_plugin.Ml2Plugin
    iniset $NEUTRON_CONF DEFAULT service_plugins akanda.neutron.plugins.ml2_neutron_plugin.L3RouterPlugin
    iniset $NEUTRON_CONF DEFAULT api_extensions_path $AKANDA_NEUTRON_DIR/akanda/neutron/extensions
    # Use rpc as notification driver instead of the default no_ops driver
    # We need the RUG to be able to get neutron's events notification like port.create.start/end
    # or router.interface.start/end to make it able to boot akanda routers
    iniset $NEUTRON_CONF DEFAULT notification_driver "neutron.openstack.common.notifier.rpc_notifier"
}

function install_akanda() {

    # akanda-rug rug-ctl requires the `blessed` package, which is not in OpenStack's global requirements,
    # so an attempt to install akanda-rug with the `setup_develop` function will fail.
    #
    # In newer versions of devstack, there is a way to disabled this behavior:
    # http://git.openstack.org/cgit/openstack-dev/devstack/commit/functions-common?id=def1534ce06409c4c70d6569ea6314a82897e28b
    #
    # For now, inject `blessed` into the global requirements so that akanda-rug can install
    echo "blessed" >> /opt/stack/requirements/global-requirements.txt

    git_clone $AKANDA_NEUTRON_REPO $AKANDA_NEUTRON_DIR $AKANDA_NEUTRON_BRANCH
    setup_develop $AKANDA_NEUTRON_DIR

    setup_develop $AKANDA_RUG_DIR
}

function _remove_subnets() {
    # We have to modify the output of net-show to allow it to be
    # parsed properly as shell variables, and we run both commands in
    # a subshell to avoid polluting the local namespace.
    (eval $(neutron $auth_args net-show -f shell $1 | sed 's/:/_/g');
        neutron $auth_args subnet-delete $subnets)

}

function pre_start_akanda() {
    typeset auth_args="--os-username $Q_ADMIN_USERNAME --os-password $SERVICE_PASSWORD --os-tenant-name $SERVICE_TENANT_NAME --os-auth-url $OS_AUTH_URL"
    neutron $auth_args net-create public --router:external

    # Remove the ipv6 subnet created automatically before adding our own.
    _remove_subnets public

    typeset public_subnet_id=$(neutron $auth_args subnet-create --ip-version 4 public 172.16.77.0/24 | grep ' id ' | awk '{ print $4 }')
    iniset $AKANDA_RUG_CONF DEFAULT external_subnet_id $public_subnet_id
    neutron $auth_args subnet-create --ip-version 6 public fdee:9f85:83be::/48

    # Point neutron-akanda at the subnet to use for floating IPs.  This requires a neutron service restart (later) to take effect.
    iniset $NEUTRON_CONF akanda floatingip_subnet $public_subnet_id

    # setup masq rule for public network
    sudo iptables -t nat -A POSTROUTING -s 172.16.77.0/24 -o $PUBLIC_INTERFACE_DEFAULT -j MASQUERADE

    neutron $auth_args net-show public | grep ' id ' | awk '{ print $4 }'

    typeset public_network_id=$(neutron $auth_args net-show public | grep ' id ' | awk '{ print $4 }')
    iniset $AKANDA_RUG_CONF DEFAULT external_network_id $public_network_id

    neutron $auth_args net-create mgt
    typeset mgt_network_id=$(neutron $auth_args net-show mgt | grep ' id ' | awk '{ print $4 }')
    iniset $AKANDA_RUG_CONF DEFAULT management_network_id $mgt_network_id

    # Remove the ipv6 subnet created automatically before adding our own.
    _remove_subnets mgt

    typeset mgt_subnet_id=$(neutron $auth_args subnet-create mgt fdca:3ba5:a17a:acda::/64 --ip-version=6 --ipv6_address_mode=slaac --enable_dhcp | grep ' id ' | awk '{ print $4 }')
    iniset $AKANDA_RUG_CONF DEFAULT management_subnet_id $mgt_subnet_id

    # Remove the private network created by devstack
    neutron $auth_args subnet-delete $PRIVATE_SUBNET_NAME
    neutron $auth_args net-delete $PRIVATE_NETWORK_NAME

    TOKEN=$(keystone token-get | grep ' id ' | get_field 2)
    die_if_not_set $LINENO TOKEN "Keystone fail to get token"

    upload_image $AKANDA_DEV_APPLIANCE $TOKEN

    typeset image_id=$(glance $auth_args image-show akanda | grep ' id ' | awk '{print $4}')

    die_if_not_set $LINENO image_id "Failed to find akanda image"
    iniset $AKANDA_RUG_CONF DEFAULT router_image_uuid $image_id

    iniset $AKANDA_RUG_CONF DEFAULT auth_url $OS_AUTH_URL
}

function start_akanda_rug() {
    screen_it ak-rug "cd $AKANDA_RUG_DIR && akanda-rug-service --config-file $AKANDA_RUG_CONF"
    echo '************************************************************'
    echo "Sleeping for a while to make sure the tap device gets set up"
    echo '************************************************************'
    sleep 10
}

function post_start_akanda() {
    echo "Creating demo user network and subnet"
    neutron --os-username demo --os-password $ADMIN_PASSWORD \
        --os-tenant-name demo --os-auth-url $OS_AUTH_URL \
        net-create thenet
    neutron --os-username demo --os-password $ADMIN_PASSWORD \
        --os-tenant-name demo --os-auth-url $OS_AUTH_URL \
        subnet-create thenet 192.168.0.0/24

    # Restart neutron so that `akanda.floatingip_subnet` is properly set
    screen_stop_service q-svc
    start_neutron_service_and_check

    # Due to a bug in security groups we need to enable udp ingress traffic
    # on port 68 to allow vms to get dhcp replies from the router.
    set_demo_tenant_sec_group_dhcp_rules
}

function stop_akanda_rug() {
    echo "Stopping the rug..."
    screen_stop_service ak-rug
    stop_process ak-rug
}

function set_neutron_user_permission() {
    # Starting from juno services users are not granted with the admin role anymore
    # but with a new `service` role.
    # Since nova policy allows only vms booted by admin users to attach ports on the
    # public networks, we need to modify the policy and allow users with the service
    # to do that too.

    local old_value='"network:attach_external_network": "rule:admin_api"'
    local new_value='"network:attach_external_network": "rule:admin_api or role:service"'
    sed -i "s/$old_value/$new_value/g" /etc/nova/policy.json
}

function set_demo_tenant_sec_group_dhcp_rules() {
    typeset auth_args="--os-username demo --os-password $OS_PASSWORD --os-tenant-name demo --os-auth-url $OS_AUTH_URL"
    neutron $auth_args security-group-rule-create --direction ingress --ethertype IPv4 --protocol udp --port-range-min 68 --port-range-max 68 default
}



if is_service_enabled ak-rug; then
    if [[ "$1" == "source" ]]; then
        # no-op
        :

    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing Akanda"
        set_neutron_user_permission
        install_akanda

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Installing Akanda"
        configure_akanda
        configure_akanda_nova
        configure_akanda_neutron
        cd $old_cwd

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing Akanda"
        pre_start_akanda
        start_akanda_rug
        post_start_akanda
    fi

    if [[ "$1" == "unstack" ]]; then
        stop_akanda_rug
    fi

    if [[ "$1" == "clean" ]]; then
        # no-op
        :
    fi
fi

