Astara Install
==============

Assumptions:
------------

You have a fully operating Openstack environment with, at least: Nova, Keystone, Glance, Neutron
The OpenStack environment has been tested and they VMs can be successfully created.
the packages git and pip should be installed

This has been tested on Ubuntu 14.04 with OpenStack installed from source. For RHEL or CentOS path names will
need to be adjusted.

Use the neutron commands to delete all VMs, routers, networks

All neutron l3 agents should be stopped and disabled. (l3, dhcp, ..)

Installation
------------

All configuration is to be performed on the controller node.

1. Set up astara user and directories::

    mkdir -p /var/log/astara /var/lib/astara /etc/astara
    useradd --home-dir "/var/lib/astara"\\
    --create-home --system --shell /bin/false astara

    chown -R astara:astara /var/log/astara /var/lib/astara /etc/astara

  Set up log rotation::


        cat >> /etc/logrotate.d/astara << EOF

        /var/log/astara/\*.log \{

          daily

          missingok

          rotate 7

          compress

          notifempty

          nocreate

        \}

        EOF

  Give astara sudo permissions::

    cat > '/etc/sudoers.d/astara_sudoers' << EOF
    Defaults:astara !requiretty

    astara ALL = (root) NOPASSWD: ALL
    EOF

2. Get the code::

    git clone git://git.openstack.org/openstack/astara

    git clone git://git.openstack.org/openstack/astara-neutron

    git clone git://git.openstack.org/openstack/astara-appliance


3. Install the code::

    # If you are not building packages and just installing locally, manually install it via pip:

    cd astara
    pip install .

    cd ../astara-neutron
    pip install .
    cd ..


4. Install astara-neutron::

    cp -r astara-neutron /var/lib/neutron/
    chown -R neutron:neutron /var/lib/neutron/astara-neutron

5. Configure Neutron:

  Make required changes to the neutron configuration file:

  In /etc/neutron/neutron.conf, set in the [DEFAULT] section:

    To use the Astara Neutron ML2 plugin change the core_plugin and service_plugins to::

        core_plugin = astara_neutron.plugins.ml2_neutron_plugin.Ml2Plugin
        service_plugins = astara_neutron.plugins.ml2_neutron_plugin.L3RouterPlugin

    And also the add the API extension path (Note: append the astara path to existing list of extension paths if you have others specified)::

        api_extensions_path = /usr/local/lib/python2.7/dist-packages/astara_neutron/extensions/

    Configure Neutron to emit event notifications::

        notification_driver  = neutron.openstack.common.notifier.rpc_notifier

  In /etc/neutron/plugins/ml2/ml2_conf.ini in the [ml2] section add::

    extension_drivers = port_security

  Ensure that l2population is enabled. In the ml2 ini file set:
  
      Add l2population to the mechanism_drivers line
      
      To the [agent] and either [vxlan] or [gre] sections add::
      
          l2_population = True

6. Configure Nova to use astara in the [DEFAULT] section of /etc/nova/nova.conf set:

  If using IPv6::

    use_ipv6=True

  In the [neutron] section of /etc/nova/nova.conf set::

    service_metadata_proxy = True

  In /etc/nova/policy.json, replace::

    "network:attach_external_network": "rule:admin_api"

  with::

    "network:attach_external_network": "rule:admin_api or role:service"

7. Start/restart Nova API to read the configuration changes::

    restart nova-api

  Restart the neutron services::

    restart neutron-server
    restart neutron-linuxbridge

  Create a management network::
    neutron net-create mgt # note the ID, it is used in the orchestrator.ini config

    neutron subnet-create --name mgt-subnet mgt fdca:3ba5:a17a:acda::/64 --ip-version=6 --ipv6_address_mode=slaac --enable_dhcp

  Create a public network::

    neutron net-create --shared --router:external public
    neutron subnet-create --name public-subnet public 172.16.0.0/24

8. Configure Astara:

  For this configuration, we assume an IPv6 Neutron network /w prefix fdca:3ba5:a17a:acda::/64 has been created to be used as the management network::

    mkdir /etc/astara
    cp astara/etc/* /etc/astara/

  Create a ssh keypair to enable ssh key based logins to the router::

    ssh-keygen

  It is best to copy the public ssh key into the astara configuration directory::

    cp ~/.ssh/id_rsa.pub /etc/astara
    chmod 600 /etc/astara

 In the astara orchestrator configuration file (/etc/astara/orchestrator.ini) make the following changes:

  In the [oslo_messaging_rabbit] section set::

    rabbit_userid = guest
    rabbit_password = guest
    rabbit_hosts = 10.0.1.4

  Set up logging::

    log_file = /var/log/astara/orchestrator.log

  Set the prefix of the existing Neutron network to be used used as management network used during subnet creation (above)::

    management_prefix = fdca:3ba5:a17a:acda::/64

  The neutron subnet id of the management subnet::

    management_subnet_id = $management_subnet_uuid

  The neutron network if of the external network::

    external_network_id=$public_network_id

  Public SSH Key used for SSH'ing into the appliance VMs as user 'astara' (this is optional)::

    ssh_public_key = $path_to_readable_ssh_pub_key #From the above step this should be /etc/astara/id_rsa.pub

  The interface driver is used for bringing up a local port on the astara control node that plugs into the management network.  This is specific to the underlying L2 implementation used, set accordingly::

    interface_driver=astara.common.linux.interface.BridgeInterfaceDriver  #For Linuxbridge
    interface_driver=astara.common.linux.interface.OVSInterfaceDriver #For OpenvSwitch

  Correct the provider rules path::

    provider_rules_path=/etc/astara/provider_rules.json

  In the [keystone_authtoken] section, configure the credentials for the keystone service tenant, specifically::

    auth_uri = http://127.0.0.1:5000     # Adjust the IP for the current installation
    project_name = service
    password = neutron
    username = neutron
    auth_url = http://127.0.0.1:35357    # Adjust the IP for the current installation

  In the [database] section, configure URL to supported oslo.db backend, ie::

    connection = mysql+pymysql://astara:astara@127.0.0.1/astara?charset=utf8


9. Create and Migrate the DB:

  Install the PyMySQL pip package::

    pip install PyMySQL
    
  And create the database set database access permissions::

    mysql -u root -pmysql -e 'CREATE DATABASE astara;'
    mysql -u root -pmysql -e "GRANT ALL PRIVILEGES ON astara.* TO 'astara'@'localhost' IDENTIFIED BY 'astara';"
    mysql -u root -pmysql -e "GRANT ALL PRIVILEGES ON astara.* TO 'astara'@'%' IDENTIFIED BY 'astara';"
    astara-dbsync --config-file /etc/astara/orchestrator.ini upgrade


10. Create or download an Appliance Image

  If you don't plan to build your own appliance image, one can be downloaded for testing at: http://tarballs.openstack.org/akanda-appliance/images/

  If you want to build one yourself instructions are found in the astara-appliance documation - https://github.com/openstack/astara/blob/master/docs/source/appliance.rst#building-a-service-vm-image-from-source

  In either case, upload the image to Glance::

    openstack image create astara --public --container-format=bare --disk-format=qcow2 --file astara.qcow2

  Note the image id for the next step

  Update /etc/astara/orchestrator.ini and set this in the [router] section::

    image_uuid=$image_uuid_in_glance

  You may also want to boot appliances with a specific nova flavor, this may be specified in the [router] section as:
  Create a new flavor::

    nova flavor-create m1.astara 6 512 3 1 --is-public True

Set the flavor in /etc/astara/orchestrator.ini::

    instance_flavor=$nova_flavor_id

11. Start astara::

      astara-orchestrator --config-file /etc/astara/orchestrator.ini

  For Ubuntu or Debian systems use the following to create an upstart script to automatically start astara-orchestrator on boot::

    cat > /etc/init/astara.conf << EOF
    description "Astara Orchestrator server"

    start on runlevel [2345]
    stop on runlevel [!2345]

    respawn

    exec start-stop-daemon --start --chuid astara --exec /usr/local/bin/astara-orchestrator -- --config-file=/etc/astara/orchestrator.ini

    EOF

  Note: For RHEL or CentOS use the command::

    sudo -u astara  /usr/local/bin/astara-orchestrator --config-file=/etc/astara/orchestrator.ini &

  Note: to automatically start the orchestrator process a systemd startup script will need to be created.
  Start the astara orchestrator process::

    start astara

Use Astara:
-----------

If you have existing routers in your environment, astara will find them and attempt to boot appliances in Nova.  If not, create a router and it should react accordingly. Otherwise use the following to create a privte network, create a router and add the network interface to the rputer::

    neutron net-create private
    neutron subnet-create --name private-subnet private 10.2.0.0/24

    neutron router-create MyRouter
    neutron router-interface-add MyRouter private

Boot a VM (replacing the <---> with the appropriate information::

    nova boot --image <VM image name> --flavor 1 --nic net-id=<private network UUID> <name>
