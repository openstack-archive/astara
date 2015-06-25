# -*- mode: shell-script -*-

# Set up default directories
AKANDA_NEUTRON_DIR=$DEST/akanda-neutron
AKANDA_NEUTRON_REPO=${AKANDA_NEUTRON_REPO:-http://github.com/stackforge/akanda-neutron.git}
AKANDA_NEUTRON_BRANCH=${AKANDA_NEUTRON_BRANCH:-master}

AKANDA_APPLIANCE_DIR=$DEST/akanda-appliance
AKANDA_APPLIANCE_REPO=${AKANDA_APPLIANCE_REPO:-http://github.com/stackforge/akanda-appliance.git}
AKANDA_APPLIANCE_BRANCH=${AKANDA_APPLIANCE_BRANCH:-master}

BUILD_AKANDA_APPLIANCE_IMAGE=${BUILD_AKANDA_APPLIANCE_IMAGE:-False}
AKANDA_DEV_APPLIANCE_URL=${AKANDA_DEV_APPLIANCE_URL:-http://akandaio.objects.dreamhost.com/akanda_cloud.qcow2}
AKANDA_DEV_APPLIANCE_FILE=${AKANDA_DEV_APPLIANCE_FILE:-$TOP_DIR/files/akanda.qcow2}
AKANDA_DEV_APPLIANCE_BUILD_PROXY=${AKANDA_DEV_APPLIANCE_BUILD_PROXY:-""}

AKANDA_HORIZON_DIR=${AKANDA_HORIZON_DIR:-$DEST/akanda-horizon}
AKANDA_HORIZON_REPO=${AKANDA_HORIZON_REPO:-http://github.com/stackforge/akanda-horizon}
AKANDA_HORIZON_BRANCH=${AKANDA_HORIZON_BRANCH:-master}

AKANDA_CONF_DIR=/etc/akanda-rug
AKANDA_RUG_CONF=$AKANDA_CONF_DIR/rug.ini

# Router instances will run as a specific Nova flavor. These values configure
# the specs of the flavor devstack will create.
ROUTER_INSTANCE_FLAVOR_ID=${ROUTER_INSTANCE_FLAVOR_ID:-135}  # NOTE(adam_g): This can be auto-generated UUID once RUG supports non-int IDs here
ROUTER_INSTANCE_FLAVOR_RAM=${ROUTER_INSTANCE_FLAVOR_RAM:-512}
ROUTER_INSTANCE_FLAVOR_DISK=${ROUTER_INSTANCE_FLAVOR_DISK:-5}
ROUTER_INSTANCE_FLAVOR_CPUS=${ROUTER_INSTANCE_FLAVOR_CPUS:-1}

PUBLIC_INTERFACE_DEFAULT='eth0'
AKANDA_RUG_MANAGEMENT_PREFIX=${RUG_MANGEMENT_PREFIX:-"fdca:3ba5:a17a:acda::/64"}
AKANDA_RUG_MANAGEMENT_PORT=${AKANDA_RUG_MANAGEMENT_PORT:-5000}
AKANDA_RUG_API_PORT=${AKANDA_RUG_API_PORT:-44250}

HORIZON_LOCAL_SETTINGS=$HORIZON_DIR/openstack_dashboard/local/local_settings.py

# Path to public ssh key that will be added to the 'akanda' users authorized_keys
# within the appliance VM.
AKANDA_APPLIANCE_SSH_PUBLIC_KEY=${AKANDA_APPLIANCE_SSH_PUBLIC_KEY:-/home/$STACK_USER/.ssh/id_rsa.pub}


function colorize_logging {
    # Add color to logging output - this is lifted from devstack's functions to colorize the non-standard
    # akanda format
    iniset $AKANDA_RUG_CONF DEFAULT logging_exception_prefix "%(color)s%(asctime)s.%(msecs)03d TRACE %(name)s [01;[00m"
    iniset $AKANDA_RUG_CONF DEFAULT logging_debug_format_suffix "[00;33mfrom (pid=%(process)d) %(funcName)s %(pathname)s:%(lineno)d[00m"
    iniset $AKANDA_RUG_CONF DEFAULT logging_default_format_string "%(asctime)s.%(msecs)03d %(color)s%(levelname)s %(name)s:%(process)s:%(processName)s:%(threadName)s [[00;36m-%(color)s] [01;35m%(color)s%(message)s[00m"
    iniset $AKANDA_RUG_CONF DEFAULT logging_context_format_string "%(asctime)s.%(msecs)03d %(color)s%(levelname)s %(name)s:%(process)s:%(processName)s:%(threadName)s [[01;36m%(request_id)s [00;36m%(user)s %(tenant)s%(color)s] [01;35m%(color)s%(message)s[00m"
}

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

    iniset $AKANDA_RUG_CONF DEFAULT management_prefix $AKANDA_RUG_MANAGEMENT_PREFIX
    iniset $AKANDA_RUG_CONF DEFAULT akanda_mgt_service_port $AKANDA_RUG_MANAGEMENT_PORT
    iniset $AKANDA_RUG_CONF DEFAULT rug_api_port $AKANDA_RUG_API_PORT

    if [[ "$Q_AGENT" == "linuxbridge" ]]; then
        iniset $AKANDA_RUG_CONF DEFAULT interface_driver "akanda.rug.common.linux.interface.BridgeInterfaceDriver"
    fi

    iniset $AKANDA_RUG_CONF DEFAULT router_ssh_public_key $AKANDA_APPLIANCE_SSH_PUBLIC_KEY

    if [ "$LOG_COLOR" == "True" ] && [ "$SYSLOG" == "False" ]; then
        colorize_logging
    fi
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

function configure_akanda_horizon() {
    # _horizon_config_set depends on this being set
    local local_settings=$HORIZON_LOCAL_SETTINGS
    for ext in $(ls $AKANDA_HORIZON_DIR/openstack_dashboard_extensions/*.py); do
        local ext_dest=$HORIZON_DIR/openstack_dashboard/local/enabled/$(basename $ext)
        rm -rf $ext_dest
        ln -s $ext $ext_dest
        # if horizon is enabled, we assume lib/horizon has been sourced and _horizon_config_set
        # is defined
        _horizon_config_set $HORIZON_LOCAL_SETTINGS "" RUG_MANAGEMENT_PREFIX \"$AKANDA_RUG_MANAGEMENT_PREFIX\"
        _horizon_config_set $HORIZON_LOCAL_SETTINGS  "" RUG_API_PORT \"$AKANDA_RUG_API_PORT\"
    done
}

function start_akanda_horizon() {
    restart_apache_server
}

function install_akanda() {
    git_clone $AKANDA_NEUTRON_REPO $AKANDA_NEUTRON_DIR $AKANDA_NEUTRON_BRANCH
    setup_develop $AKANDA_NEUTRON_DIR
    setup_develop $AKANDA_RUG_DIR

    if [ "$BUILD_AKANDA_APPLIANCE_IMAGE" == "True" ]; then
        git_clone $AKANDA_APPLIANCE_REPO $AKANDA_APPLIANCE_DIR $AKANDA_APPLIANCE_BRANCH
    fi

    if is_service_enabled horizon; then
        git_clone $AKANDA_HORIZON_REPO $AKANDA_HORIZON_DIR $AKANDA_HORIZON_BRANCH
        setup_develop $AKANDA_HORIZON_DIR
    fi
}

function create_akanda_nova_flavor() {
    nova flavor-create akanda $ROUTER_INSTANCE_FLAVOR_ID \
      $ROUTER_INSTANCE_FLAVOR_RAM $ROUTER_INSTANCE_FLAVOR_DISK \
      $ROUTER_INSTANCE_FLAVOR_CPUS
    iniset $AKANDA_RUG_CONF DEFAULT router_instance_flavor $ROUTER_INSTANCE_FLAVOR_ID
}

function _remove_subnets() {
    # Attempt to delete subnets associated with a network.
    # We have to modify the output of net-show to allow it to be
    # parsed properly as shell variables, and we run both commands in
    # a subshell to avoid polluting the local namespace.
    (eval $(neutron $auth_args net-show -f shell $1 | sed 's/:/_/g');
        neutron $auth_args subnet-delete $subnets || true)
}

function pre_start_akanda() {
    typeset auth_args="--os-username $Q_ADMIN_USERNAME --os-password $SERVICE_PASSWORD --os-tenant-name $SERVICE_TENANT_NAME --os-auth-url $OS_AUTH_URL"
    if ! neutron net-show $PUBLIC_NETWORK_NAME; then
        neutron $auth_args net-create $PUBLIC_NETWORK_NAME --router:external
    fi

    # Remove the ipv6 subnet created automatically before adding our own.
    # NOTE(adam_g): For some reason this fails the first time and needs to be repeated?
    _remove_subnets $PUBLIC_NETWORK_NAME ; _remove_subnets $PUBLIC_NETWORK_NAME

    typeset public_subnet_id=$(neutron $auth_args subnet-create --ip-version 4 $PUBLIC_NETWORK_NAME 172.16.77.0/24 | grep ' id ' | awk '{ print $4 }')
    iniset $AKANDA_RUG_CONF DEFAULT external_subnet_id $public_subnet_id
    neutron $auth_args subnet-create --ip-version 6 $PUBLIC_NETWORK_NAME fdee:9f85:83be::/48

    # Point neutron-akanda at the subnet to use for floating IPs.  This requires a neutron service restart (later) to take effect.
    iniset $NEUTRON_CONF akanda floatingip_subnet $public_subnet_id

    # setup masq rule for public network
    sudo iptables -t nat -A POSTROUTING -s 172.16.77.0/24 -o $PUBLIC_INTERFACE_DEFAULT -j MASQUERADE

    neutron $auth_args net-show $PUBLIC_NETWORK_NAME | grep ' id ' | awk '{ print $4 }'

    typeset public_network_id=$(neutron $auth_args net-show $PUBLIC_NETWORK_NAME | grep ' id ' | awk '{ print $4 }')
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

    local akanda_dev_image_src=""
    if [ "$BUILD_AKANDA_APPLIANCE_IMAGE" == "True" ]; then
        if [[ $(type -P disk-image-create) == "" ]]; then
            pip_install "diskimage-builder<0.1.43"
        fi
        # Point DIB at the devstack checkout of the akanda-appliance repo
        DIB_REPOLOCATION_akanda=$AKANDA_APPLIANCE_DIR \
        DIB_REPOREF_akanda="$(cd $AKANDA_APPLIANCE_DIR && git rev-parse HEAD)" \
        DIB_AKANDA_APPLIANCE_DEBUG_USER=$ADMIN_USERNAME \
        DIB_AKANDA_APPLIANCE_DEBUG_PASSWORD=$ADMIN_PASSWORD \
        http_proxy=$AKANDA_DEV_APPLIANCE_BUILD_PROXY \
        ELEMENTS_PATH=$AKANDA_APPLIANCE_DIR/diskimage-builder/elements \
        DIB_RELEASE=jessie DIB_EXTLINUX=1 disk-image-create debian vm akanda debug-user \
        -o $TOP_DIR/files/akanda
        akanda_dev_image_src=$AKANDA_DEV_APPLIANCE_FILE
    else
        akanda_dev_image_src=$AKANDA_DEV_APPLIANCE_URL
    fi

    TOKEN=$(keystone token-get | grep ' id ' | get_field 2)
    die_if_not_set $LINENO TOKEN "Keystone fail to get token"
    upload_image $akanda_dev_image_src $TOKEN

    local image_name=$(basename $akanda_dev_image_src | cut -d. -f1)
    typeset image_id=$(glance $auth_args image-show $image_name | grep ' id ' | awk '{print $4}')

    die_if_not_set $LINENO image_id "Failed to find akanda image"
    iniset $AKANDA_RUG_CONF DEFAULT router_image_uuid $image_id

    iniset $AKANDA_RUG_CONF DEFAULT auth_url $OS_AUTH_URL

    if is_service_enabled horizon; then
        # _horizon_config_set depends on this being set
        local local_settings=$HORIZON_LOCAL_SETTINGS
        _horizon_config_set $HORIZON_LOCAL_SETTINGS "" ROUTER_IMAGE_UUID \"$image_id\"
    fi

    create_akanda_nova_flavor
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
    if [[ "$USE_SCREEN" == "True" ]]; then
        screen_stop_service q-svc
    else
        stop_process q-svc
    fi
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


function check_prereqs() {
    # Fail devstack as early as possible if system does not satisfy some known
    # prerequisites
    if [ ! -e "$AKANDA_APPLIANCE_SSH_PUBLIC_KEY" ]; then
        die $LINENO "Public SSH key not found at $AKANDA_APPLIANCE_SSH_PUBLIC_KEY. Please copy one there or " \
                    "set AKANDA_APPLIANCE_SSH_PUBLIC_KEY accordingly."

    fi
}


if is_service_enabled ak-rug; then
    if [[ "$1" == "source" ]]; then
        check_prereqs

    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing Akanda"
        set_neutron_user_permission
        install_akanda

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Installing Akanda"
        configure_akanda
        configure_akanda_nova
        configure_akanda_neutron
        if is_service_enabled horizon; then
            configure_akanda_horizon
        fi
        cd $old_cwd

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing Akanda"
        pre_start_akanda
        start_akanda_rug
        if is_service_enabled horizon; then
            start_akanda_horizon
        fi
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

