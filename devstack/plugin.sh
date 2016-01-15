# -*- mode: shell-script -*-

# Set up default directories
ASTARA_DIR=${ASTARA_DIR:-$DEST/astara}
ASTARA_CACHE_DIR=${ASTARA_CACHE_DIR:-/var/cache/astara}
ASTARA_NEUTRON_DIR=${ASTARA_NEUTRON_DIR:-$DEST/astara-neutron}
ASTARA_NEUTRON_REPO=${ASTARA_NEUTRON_REPO:-${GIT_BASE}/openstack/astara-neutron.git}
ASTARA_NEUTRON_BRANCH=${ASTARA_NEUTRON_BRANCH:-master}

ASTARA_APPLIANCE_DIR=${ASTARA_APPLIANCE_DIR:-$DEST/astara-appliance}
ASTARA_APPLIANCE_REPO=${ASTARA_APPLIANCE_REPO:-${GIT_BASE}/openstack/astara-appliance.git}
ASTARA_APPLIANCE_BRANCH=${ASTARA_APPLIANCE_BRANCH:-master}

BUILD_ASTARA_APPLIANCE_IMAGE=$(trueorfalse False BUILD_ASTARA_APPLIANCE_IMAGE)
ASTARA_DEV_APPLIANCE_URL=${ASTARA_DEV_APPLIANCE_URL:-http://tarballs.openstack.org/astara-appliance/images/astara_appliance.qcow2}
ASTARA_DEV_APPLIANCE_FILE=${ASTARA_DEV_APPLIANCE_FILE:-$TOP_DIR/files/astara.qcow2}
ASTARA_DEV_APPLIANCE_BUILD_PROXY=${ASTARA_DEV_APPLIANCE_BUILD_PROXY:-""}
ASTARA_DEV_APPLIANCE_ENABLED_DRIVERS="router,loadbalancer"

ASTARA_HORIZON_DIR=${ASTARA_HORIZON_DIR:-$DEST/astara-horizon}
ASTARA_HORIZON_REPO=${ASTARA_HORIZON_REPO:-${GIT_BASE}/openstack/astara-horizon}
ASTARA_HORIZON_BRANCH=${ASTARA_HORIZON_BRANCH:-master}

ASTARA_CONF_DIR=/etc/astara
ASTARA_CONF=$ASTARA_CONF_DIR/orchestrator.ini

# Router instances will run as a specific Nova flavor. These values configure
# the specs of the flavor devstack will create.
ROUTER_INSTANCE_FLAVOR_ID=${ROUTER_INSTANCE_FLAVOR_ID:-135}  # NOTE(adam_g): This can be auto-generated UUID once RUG supports non-int IDs here
ROUTER_INSTANCE_FLAVOR_RAM=${ROUTER_INSTANCE_FLAVOR_RAM:-512}
ROUTER_INSTANCE_FLAVOR_DISK=${ROUTER_INSTANCE_FLAVOR_DISK:-5}
ROUTER_INSTANCE_FLAVOR_CPUS=${ROUTER_INSTANCE_FLAVOR_CPUS:-1}

PUBLIC_INTERFACE_DEFAULT='eth0'
ASTARA_MANAGEMENT_PREFIX=${ASTARA_MANAGEMENT_PREFIX:-"fdca:3ba5:a17a:acda::/64"}
ASTARA_MANAGEMENT_PORT=${ASTARA_MANAGEMENT_PORT:-5000}
ASTARA_API_PORT=${ASTARA_API_PORT:-44250}

HORIZON_LOCAL_SETTINGS=$HORIZON_DIR/openstack_dashboard/local/local_settings.py

# Path to public ssh key that will be added to the 'astara' users authorized_keys
# within the appliance VM.
ASTARA_APPLIANCE_SSH_PUBLIC_KEY=${ASTARA_APPLIANCE_SSH_PUBLIC_KEY:-$HOME/.ssh/id_rsa.pub}

ASTARA_COORDINATION_ENABLED=$(trueorfalse True ASTARA_COORDINATION_ENABLED)
ASTARA_COORDINATION_URL=${ASTARA_COORDINATION_URL:-memcached://localhost:11211}

function colorize_logging {
    # Add color to logging output - this is lifted from devstack's functions to colorize the non-standard
    # astara format
    iniset $ASTARA_CONF DEFAULT logging_exception_prefix "%(color)s%(asctime)s.%(msecs)03d TRACE %(name)s [01;[00m"
    iniset $ASTARA_CONF DEFAULT logging_debug_format_suffix "[00;33mfrom (pid=%(process)d) %(funcName)s %(pathname)s:%(lineno)d[00m"
    iniset $ASTARA_CONF DEFAULT logging_default_format_string "%(asctime)s.%(msecs)03d %(color)s%(levelname)s %(name)s:%(process)s:%(processName)s:%(threadName)s [[00;36m-%(color)s] [01;35m%(color)s%(message)s[00m"
    iniset $ASTARA_CONF DEFAULT logging_context_format_string "%(asctime)s.%(msecs)03d %(color)s%(levelname)s %(name)s:%(process)s:%(processName)s:%(threadName)s [[01;36m%(request_id)s [00;36m%(user)s %(tenant)s%(color)s] [01;35m%(color)s%(message)s[00m"
}

function configure_astara() {
    if [[ ! -d $ASTARA_CONF_DIR ]]; then
        sudo mkdir -p $ASTARA_CONF_DIR
    fi
    sudo chown $STACK_USER $ASTARA_CONF_DIR

    sudo mkdir -p $ASTARA_CACHE_DIR
    sudo chown $STACK_USER $ASTARA_CACHE_DIR

    if [[ ! -d $ASTARA_CONF_DIR/rootwrap.d ]]; then
        sudo mkdir -p $ASTARA_CONF_DIR/rootwrap.d
    fi

    sudo cp $ASTARA_DIR/etc/rootwrap.conf $ASTARA_CONF_DIR
    sudo cp $ASTARA_DIR/etc/rootwrap.d/* $ASTARA_CONF_DIR/rootwrap.d/

    cp $ASTARA_DIR/etc/orchestrator.ini $ASTARA_CONF
    iniset $ASTARA_CONF DEFAULT verbose True
    configure_auth_token_middleware $ASTARA_CONF $Q_ADMIN_USERNAME $ASTARA_CACHE_DIR
    iniset_rpc_backend astara $ASTARA_CONF

    iniset $ASTARA_CONF DEFAULT control_exchange "neutron"
    iniset $ASTARA_CONF DEFAULT boot_timeout "6000"
    iniset $ASTARA_CONF DEFAULT num_worker_processes "2"
    iniset $ASTARA_CONF DEFAULT num_worker_threads "2"
    iniset $ASTARA_CONF DEFAULT reboot_error_threshold "2"

    iniset $ASTARA_CONF DEFAULT management_prefix $ASTARA_MANAGEMENT_PREFIX
    iniset $ASTARA_CONF DEFAULT astara_mgt_service_port $ASTARA_MANAGEMENT_PORT
    iniset $ASTARA_CONF DEFAULT rug_api_port $ASTARA_API_PORT

    if [[ "$Q_AGENT" == "linuxbridge" ]]; then
        iniset $ASTARA_CONF DEFAULT interface_driver "astara.common.linux.interface.BridgeInterfaceDriver"
    fi

    iniset $ASTARA_CONF DEFAULT ssh_public_key $ASTARA_APPLIANCE_SSH_PUBLIC_KEY

    iniset $ASTARA_CONF database connection `database_connection_url astara`

    if [ "$LOG_COLOR" == "True" ] && [ "$SYSLOG" == "False" ]; then
        colorize_logging
    fi

    if [[ "$ASTARA_COORDINATION_ENABLED" == "True" ]]; then
        iniset $ASTARA_CONF coordination enabled True
        iniset $ASTARA_CONF coordination url $ASTARA_COORDINATION_URL
    fi

    # NOTE(adam_g): This is temporary and can be removed after mitaka-1
    iniset $ASTARA_CONF DEFAULT astara_boot_command akanda-configure-management
}

function configure_astara_nova() {
    iniset $NOVA_CONF neutron service_metadata_proxy True
    iniset $NOVA_CONF DEFAULT use_ipv6 True
}

function configure_astara_neutron() {
    iniset $NEUTRON_CONF DEFAULT core_plugin astara_neutron.plugins.ml2_neutron_plugin.Ml2Plugin
    iniset $NEUTRON_CONF DEFAULT service_plugins astara_neutron.plugins.ml2_neutron_plugin.L3RouterPlugin
    iniset $NEUTRON_CONF DEFAULT api_extensions_path $ASTARA_NEUTRON_DIR/astara_neutron/extensions
    # Use rpc as notification driver instead of the default no_ops driver
    # We need the RUG to be able to get neutron's events notification like port.create.start/end
    # or router.interface.start/end to make it able to boot astara routers
    iniset $NEUTRON_CONF DEFAULT notification_driver "neutron.openstack.common.notifier.rpc_notifier"
}

function configure_astara_horizon() {
    # _horizon_config_set depends on this being set
    local local_settings=$HORIZON_LOCAL_SETTINGS
    for ext in $(ls $ASTARA_HORIZON_DIR/openstack_dashboard_extensions/*.py); do
        local ext_dest=$HORIZON_DIR/openstack_dashboard/local/enabled/$(basename $ext)
        rm -rf $ext_dest
        ln -s $ext $ext_dest
        # if horizon is enabled, we assume lib/horizon has been sourced and _horizon_config_set
        # is defined
        _horizon_config_set $HORIZON_LOCAL_SETTINGS "" RUG_MANAGEMENT_PREFIX \"$ASTARA_MANAGEMENT_PREFIX\"
        _horizon_config_set $HORIZON_LOCAL_SETTINGS  "" RUG_API_PORT \"$ASTARA_API_PORT\"
    done
}

function start_astara_horizon() {
    restart_apache_server
}

function install_astara() {
    git_clone $ASTARA_NEUTRON_REPO $ASTARA_NEUTRON_DIR $ASTARA_NEUTRON_BRANCH
    setup_develop $ASTARA_NEUTRON_DIR
    setup_develop $ASTARA_DIR

    # temp hack to add blessed durring devstack installs so that rug-ctl browse works out of the box
    pip_install blessed

    if [ "$BUILD_ASTARA_APPLIANCE_IMAGE" == "True" ]; then
        git_clone $ASTARA_APPLIANCE_REPO $ASTARA_APPLIANCE_DIR $ASTARA_APPLIANCE_BRANCH
    fi

    if is_service_enabled horizon; then
        git_clone $ASTARA_HORIZON_REPO $ASTARA_HORIZON_DIR $ASTARA_HORIZON_BRANCH
        setup_develop $ASTARA_HORIZON_DIR
    fi
}

function _auth_args() {
    local username=$1
    local password=$2
    local tenant_name=$3
    local auth_args="--os-username $username --os-password $password --os-auth-url $OS_AUTH_URL"
    if [ "$OS_IDENTITY_API_VERSION" -eq "3" ]; then
        auth_args="$auth_args --os-project-name $tenant_name"
    else
        auth_args="$auth_args --os-tenant-name $tenant_name"
    fi
    echo "$auth_args"
}

function create_astara_nova_flavor() {
    openstack --os-cloud=devstack-admin flavor create astara \
      --id $ROUTER_INSTANCE_FLAVOR_ID --ram $ROUTER_INSTANCE_FLAVOR_RAM \
      --disk $ROUTER_INSTANCE_FLAVOR_DISK --vcpus $ROUTER_INSTANCE_FLAVOR_CPUS
    iniset $ASTARA_CONF router instance_flavor $ROUTER_INSTANCE_FLAVOR_ID
}

function _remove_subnets() {
    # Attempt to delete subnets associated with a network.
    # We have to modify the output of net-show to allow it to be
    # parsed properly as shell variables, and we run both commands in
    # a subshell to avoid polluting the local namespace.
    (eval $(neutron $auth_args net-show -f shell $1 | sed 's/:/_/g');
        neutron $auth_args subnet-delete $subnets || true)
}

function pre_start_astara() {
    # Create and init the database
    recreate_database astara
    astara-dbsync --config-file $ASTARA_CONF upgrade

    local auth_args="$(_auth_args $Q_ADMIN_USERNAME $SERVICE_PASSWORD $SERVICE_TENANT_NAME)"

    # having these set by something else in devstack will override those that we pass on
    # CLI.
    unset OS_TENANT_NAME OS_PROJECT_NAME

    if ! neutron $auth_args net-show $PUBLIC_NETWORK_NAME; then
        neutron $auth_args net-create $PUBLIC_NETWORK_NAME --router:external
    fi

    # Remove the ipv6 subnet created automatically before adding our own.
    # NOTE(adam_g): For some reason this fails the first time and needs to be repeated?
    _remove_subnets $PUBLIC_NETWORK_NAME ; _remove_subnets $PUBLIC_NETWORK_NAME

    typeset public_subnet_id=$(neutron $auth_args subnet-create --ip-version 4 $PUBLIC_NETWORK_NAME 172.16.77.0/24 | grep ' id ' | awk '{ print $4 }')
    iniset $ASTARA_CONF DEFAULT external_subnet_id $public_subnet_id
    neutron $auth_args subnet-create --ip-version 6 $PUBLIC_NETWORK_NAME fdee:9f85:83be::/48

    # Point neutron-astara at the subnet to use for floating IPs.  This requires a neutron service restart (later) to take effect.
    iniset $NEUTRON_CONF astara floatingip_subnet $public_subnet_id

    # setup masq rule for public network
    sudo iptables -t nat -A POSTROUTING -s 172.16.77.0/24 -o $PUBLIC_INTERFACE_DEFAULT -j MASQUERADE

    neutron $auth_args net-show $PUBLIC_NETWORK_NAME | grep ' id ' | awk '{ print $4 }'

    typeset public_network_id=$(neutron $auth_args net-show $PUBLIC_NETWORK_NAME | grep ' id ' | awk '{ print $4 }')
    iniset $ASTARA_CONF DEFAULT external_network_id $public_network_id

    neutron $auth_args net-create mgt
    typeset mgt_network_id=$(neutron $auth_args net-show mgt | grep ' id ' | awk '{ print $4 }')
    iniset $ASTARA_CONF DEFAULT management_network_id $mgt_network_id

    # Remove the ipv6 subnet created automatically before adding our own.
    _remove_subnets mgt

    local subnet_create_args=""
    if [[ "$ASTARA_MANAGEMENT_PREFIX" =~ ':' ]]; then
        subnet_create_args="--ip-version=6 --ipv6_address_mode=slaac --enable_dhcp"
    fi
    typeset mgt_subnet_id=$(neutron $auth_args subnet-create mgt $ASTARA_MANAGEMENT_PREFIX $subnet_create_args | grep ' id ' | awk '{ print $4 }')
    iniset $ASTARA_CONF DEFAULT management_subnet_id $mgt_subnet_id

    # Remove the private network created by devstack
    neutron $auth_args subnet-delete $PRIVATE_SUBNET_NAME
    neutron $auth_args net-delete $PRIVATE_NETWORK_NAME

    local astara_dev_image_src=""
    local lb_element=""

    if [ "$BUILD_ASTARA_APPLIANCE_IMAGE" == "True" ]; then
        if [[ $(type -P disk-image-create) == "" ]]; then
            pip_install "diskimage-builder"
        fi

        if [[ "$ASTARA_DEV_APPLIANCE_ENABLED_DRIVERS" =~ "loadbalancer" ]]; then
            # We can make this more configurable as we add more LB backends
            lb_element="nginx"
        fi

        # Point DIB at the devstack checkout of the astara-appliance repo
        DIB_REPOLOCATION_astara=$ASTARA_APPLIANCE_DIR \
        DIB_REPOREF_astara="$(cd $ASTARA_APPLIANCE_DIR && git rev-parse HEAD)" \
        DIB_ASTARA_APPLIANCE_DEBUG_USER=$ADMIN_USERNAME \
        DIB_ASTARA_APPLIANCE_DEBUG_PASSWORD=$ADMIN_PASSWORD \
        DIB_ASTARA_ADVANCED_SERVICES=$ASTARA_DEV_APPLIANCE_ENABLED_DRIVERS \
        http_proxy=$ASTARA_DEV_APPLIANCE_BUILD_PROXY \
        ELEMENTS_PATH=$ASTARA_APPLIANCE_DIR/diskimage-builder/elements \
        DIB_RELEASE=jessie DIB_EXTLINUX=1 disk-image-create debian vm astara debug-user $lb_element \
        -o $TOP_DIR/files/astara
        astara_dev_image_src=$ASTARA_DEV_APPLIANCE_FILE
    else
        astara_dev_image_src=$ASTARA_DEV_APPLIANCE_URL
    fi

    upload_image $astara_dev_image_src

    local image_name=$(basename $astara_dev_image_src | cut -d. -f1)
    typeset image_id=$(glance $auth_args image-list | grep $image_name | get_field 1)

    die_if_not_set $LINENO image_id "Failed to find astara image"
    iniset $ASTARA_CONF router image_uuid $image_id

    # NOTE(adam_g): Currently we only support keystone v2 auth so we need to
    # hardcode the auth url accordingly. See (LP: #1492654)
    iniset $ASTARA_CONF DEFAULT auth_url $KEYSTONE_AUTH_PROTOCOL://$KEYSTONE_AUTH_HOST:5000/v2.0

    if is_service_enabled horizon; then
        # _horizon_config_set depends on this being set
        local local_settings=$HORIZON_LOCAL_SETTINGS
        _horizon_config_set $HORIZON_LOCAL_SETTINGS "" ROUTER_IMAGE_UUID \"$image_id\"
    fi

    create_astara_nova_flavor

    # Restart neutron so that `astara.floatingip_subnet` is properly set
    if [[ "$USE_SCREEN" == "True" ]]; then
        screen_stop_service q-svc
    else
        stop_process q-svc
    fi
    start_neutron_service_and_check
    sleep 10
}

function start_astara() {
    screen_it astara "cd $ASTARA_DIR && astara-orchestrator --config-file $ASTARA_CONF"
    echo '************************************************************'
    echo "Sleeping for a while to make sure the tap device gets set up"
    echo '************************************************************'
    sleep 10
}

function post_start_astara() {
    echo "Creating demo user network and subnet"
    local auth_args="$(_auth_args demo $OS_PASSWORD demo)"
    neutron $auth_args net-create thenet
    neutron $auth_args subnet-create thenet $FIXED_RANGE

    # Open all traffic on the private CIDR
    set_demo_tenant_sec_group_private_traffic
}

function stop_astara() {
    echo "Stopping astara..."
    screen_stop_service astara
    stop_process astara
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

function set_demo_tenant_sec_group_private_traffic() {
    local auth_args="$(_auth_args demo $OS_PASSWORD demo)"
    neutron $auth_args security-group-rule-create --direction ingress --remote-ip-prefix $FIXED_RANGE default
}


function configure_astara_ssh_keypair {
    if [[ ! -e $ASTARA_APPLIANCE_SSH_PUBLIC_KEY ]]; then
        if [[ ! -d $(dirname $ASTARA_APPLIANCE_SSH_PUBLIC_KEY) ]]; then
            mkdir -p $(dirname $ASTARA_APPLIANCE_SSH_PUBLIC_KEY)
        fi
         echo -e 'n\n' | ssh-keygen -q -t rsa -P '' -f ${ASTARA_APPLIANCE_SSH_PUBLIC_KEY%.*}
    fi
}


if is_service_enabled astara; then
    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        configure_astara_ssh_keypair

    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing Astara"
        set_neutron_user_permission
        install_astara

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Installing Astara"
        configure_astara
        configure_astara_nova
        configure_astara_neutron
        if is_service_enabled horizon; then
            configure_astara_horizon
        fi
        cd $old_cwd

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing Astara"
        pre_start_astara
        start_astara
        if is_service_enabled horizon; then
            start_astara_horizon
        fi
        post_start_astara
    fi

    if [[ "$1" == "unstack" ]]; then
        stop_astara
    fi

    if [[ "$1" == "clean" ]]; then
        # no-op
        :
    fi
fi

