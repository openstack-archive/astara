.. _install_astara:

Astara Installation
===================

Assumptions
------------

You have a fully operating Openstack environment with, at least: Nova, Keystone, Glance, Neutron
The OpenStack environment has been tested and they VMs can be successfully created.
the packages git and pip should be installed

This has been tested on Ubuntu 14.04 with OpenStack installed from source. For RHEL or CentOS path names will
need to be adjusted. These instructions assume they are performed by the root user, whose home directory is /root. 
If another user does the installation some adjustment in the paths may be needed. This user will need sudo access
and most commands will need to be prepended with sudo.

Use the neutron commands to delete all VMs, routers, networks

All neutron l3 agents should be stopped and disabled. (l3, dhcp, ..)

Installation
------------

All configuration is to be performed on the controller node.

1. Set up astara user and directories::

    mkdir -p /var/log/astara /var/lib/astara /etc/astara
    useradd --home-dir "/var/lib/astara" --create-home --system --shell /bin/false astara

    chown -R astara:astara /var/log/astara /var/lib/astara /etc/astara

  Set up log rotation::


        cat >> /etc/logrotate.d/astara << EOF

        /var/log/astara/*.log {

          daily

          missingok

          rotate 7

          compress

          notifempty

          nocreate

        }

        EOF

  Give astara sudo permissions::

    cat > '/etc/sudoers.d/astara_sudoers' << EOF
    Defaults:astara !requiretty

    astara ALL = (root) NOPASSWD: /usr/local/bin/astara-rootwrap  /etc/astara/rootwrap.conf *

    EOF

2. Get the code::

    cd ~
    git clone git://git.openstack.org/openstack/astara
    git clone git://git.openstack.org/openstack/astara-neutron
    git clone git://git.openstack.org/openstack/astara-appliance


3. Install the code::

    # If you are not building packages and just installing locally, manually install it via pip:

    cd ~/astara
    pip install .

    cd ~/astara-neutron
    pip install .
    cd ~

4. Configure Neutron:

  Make required changes to the neutron configuration file:

  In /etc/neutron/neutron.conf, set in the [DEFAULT] section:

    To use the Astara Neutron ML2 plugin change the core_plugin and service_plugins to::

        core_plugin = astara_neutron.plugins.ml2_neutron_plugin.Ml2Plugin
        service_plugins = astara_neutron.plugins.ml2_neutron_plugin.L3RouterPlugin

    And also the add the API extension path (Note: append the astara path to existing list of extension paths if you have others specified)::

        api_extensions_path = /usr/local/lib/python2.7/dist-packages/astara_neutron/extensions/

    Note: the path shown will vary with the distribution for Ubuntu it will be /usr/lib/python2.7/dist-packages/astara_neutron/extensions/ for Red Hat installations this path will be different.

    Configure Neutron to emit event notifications::

        notification_driver  = neutron.openstack.common.notifier.rpc_notifier

  In /etc/neutron/plugins/ml2/ml2_conf.ini in the [ml2] section add::

    extension_drivers = port_security

  Ensure that l2population is enabled. On all nodes running the l2 agent, either Linuxbridge or OpenvSwitch (namely the compute nodes and nodes running the orchestrator process), in the ml2 ini file set:

      Add l2population to the mechanism_drivers line

      To the [agent] sections add::

          l2_population = True

      Depending on the layer 2 technology used in your OpenStack environment to enable layer 2 population additional parameters may need to be set. Check the OpenStack configuration guide for information about additional layer 2 setting for the layer 2 type and to tenant isolation type (VLAN, VXLAN of GRE) being used.

5. Configure Nova to use astara in the [DEFAULT] section of /etc/nova/nova.conf set:

  If using IPv6::

    use_ipv6=True

  In the [neutron] section of /etc/nova/nova.conf set::

    service_metadata_proxy = True

  In /etc/nova/policy.json, replace::

    "network:attach_external_network": "rule:admin_api"

  with::

    "network:attach_external_network": "rule:admin_api or role:service"

6. Start/restart Nova API to read the configuration changes::

    restart nova-api

  Restart the neutron services::

    restart neutron-server
    restart neutron-linuxbridge

  Stop and disable any L3 agents such as the DHCP agent, L3 agent or the metadata agent.

  Create a management network::

    neutron net-create mgt # note the ID, it is used in the orchestrator.ini config
    neutron subnet-create --name mgt-subnet mgt fdca:3ba5:a17a:acda::/64 --ip-version=6 --ipv6_address_mode=slaac --enable_dhcp

  Create a public network::

    neutron net-create --shared --router:external public
    neutron subnet-create --name public-subnet public 172.16.0.0/24

7. Configure Astara:

  For this configuration, we assume an IPv6 Neutron network /w prefix fdca:3ba5:a17a:acda::/64 has been created to be used as the management network::

    mkdir /etc/astara
    cp -r ~/astara/etc/* /etc/astara/
    mv /etc/astara/orchestrator.ini.sample /etc/astara/orchestrator.ini
    chown astara:astara /etc/astara/*.{ini,json}

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

   The neutron subnet id of the management network and subnet::

     management_net_id = $management_net_uuid
     management_subnet_id = $management_subnet_uuid

   The neutron network if of the external network::

     external_network_id=$public_network_id
     external_subnet_id=$public_subnet_id


   Public SSH Key used for SSH'ing into the appliance VMs as user 'astara' (this is optional)::

     ssh_public_key = $path_to_readable_ssh_pub_key #From the above step this should be /etc/astara/id_rsa.pub

   The interface driver is used for bringing up a local port on the astara control node that plugs into the management network.  This is specific to the underlying L2 implementation used, set accordingly::

     interface_driver=astara.common.linux.interface.BridgeInterfaceDriver  #For Linuxbridge
     interface_driver=astara.common.linux.interface.OVSInterfaceDriver #For OpenvSwitch

   Correct the provider rules path::

     provider_rules_path=/etc/astara/provider_rules.json

   In the [keystone_authtoken] section, configure the credentials for the keystone service tenant as configured in your environment, specifically::

     auth_uri = http://127.0.0.1:5000     # Adjust the IP for the current installation
     project_name = service
     password = neutron
     username = neutron
     auth_url = http://127.0.0.1:35357    # Adjust the IP for the current installation
     auth_plugin = password

   In the [database] section, configure URL to supported oslo.db backend, ie::

     connection = mysql+pymysql://astara:astara@127.0.0.1/astara?charset=utf8


8. Create and Migrate the DB:

  Install the PyMySQL pip package::

    pip install PyMySQL

  And create the database set database access permissions::

    mysql -u root -pmysql -e 'CREATE DATABASE astara;'
    mysql -u root -pmysql -e "GRANT ALL PRIVILEGES ON astara.* TO 'astara'@'localhost' IDENTIFIED BY 'astara';"
    mysql -u root -pmysql -e "GRANT ALL PRIVILEGES ON astara.* TO 'astara'@'%' IDENTIFIED BY 'astara';"
    astara-dbsync --config-file /etc/astara/orchestrator.ini upgrade


9. Create or download an Appliance Image

  If you don't plan to build your own appliance image, one can be downloaded for testing at: http://tarballs.openstack.org/akanda-appliance/images/

  If you want to build one yourself instructions are found in the :ref:`appliance documentation`
  In either case, upload the image to Glance (this command must be performed in the directory where the image was downloaded/created)::

    openstack image create astara --public --container-format=bare --disk-format=qcow2 --file astara.qcow2

  Note the image id for the next step

  Update /etc/astara/orchestrator.ini and set this in the [router] section::

    image_uuid=$image_uuid_in_glance

  You may also want to boot appliances with a specific nova flavor, this may be specified in the [router] section as:
  Create a new flavor::

    nova flavor-create m1.astara 6 512 3 1 --is-public True

  Set the flavor in /etc/astara/orchestrator.ini::

    instance_flavor=$nova_flavor_id

10. Start astara::

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

Use Astara
-----------

If you have existing routers in your environment, astara will find them and attempt to boot appliances in Nova.  If not, create a router and it should react accordingly. Otherwise use the following to create a privte network, create a router and add the network interface to the rputer::

    neutron net-create private
    neutron subnet-create --name private-subnet private 10.2.0.0/24

    neutron router-create MyRouter
    neutron router-interface-add MyRouter private

Boot a VM (replacing the <---> with the appropriate information)::

    nova boot --image <VM image name> --flavor 1 --nic net-id=<private network UUID> <name>

At this time sourcing the admin's credentials and using the command::

    nova list --all-tenants

Output similar to::

    +--------------------------------------+------------------------------------------------+----------------------------------+--------+------------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ID                                   | Name                                           | Tenant ID                        | Status | Task State | Power State | Networks                                                                                                                                                                                                                                                                                 |
    +--------------------------------------+------------------------------------------------+----------------------------------+--------+------------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

    | 1003335d-640c-4492-8054-80c4d23f9552 | Three                                          | fbf54d3e3fc544a7895701d27139489e | ACTIVE | -          | Running     | private1=10.3.0.3, fdd6:a1fa:cfa8:f4d0:f816:3eff:fed6:2e3b                                                                                                                                                                                                                               |
    | e75a0429-15cb-41a2-ae7b-890315b75922 | ak-router-6aa27c79-8ed4-4c59-ae83-4c4da725b3ec | d9aa8deb2d2c489e81eb93f30a5b63e8 | ACTIVE | -          | Running     | private1=fdd6:a1fa:cfa8:f4d0:f816:3eff:feab:c96b; public=fdd6:a1fa:cfa8:b59a:f816:3eff:feb4:29e6; private=fdd6:a1fa:cfa8:eefe:f816:3eff:fe3e:a5e9; mgt=fdd6:a1fa:cfa8:d5ff:f816:3eff:fe3f:4f95, fdca:3ba5:a17a:acda:f816:3eff:fe3f:4f95 |
    +--------------------------------------+------------------------------------------------+----------------------------------+--------+------------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

The line with the ak-router shows that astara has built the router VM. Further operation and debug information can be found in the :ref:`operator tools<operator_tools>` section.

.. _cluster_astara:

Clustering astara-orchestrator
------------------------------

The ``astara-orchestartor`` service supports clustering among multiple processes spanning multiple nodes to provide active/active clustering for
purposes of load-distribution and high-availability (HA). In this setup, multiple ``astara-orchestrator`` processes form a distributed hash ring,
in which each is responsible for orchestrating a subset of virtual appliances.  When one ``astara-orchestrator`` falls offline, management of
its resources are redistributed to remaining nodes.  This feature requires the use of an external coordination service (ie, zookeeper),
as provided by the `tooz library <http://docs.openstack.org/developer/tooz/>`_.  To find out more about which services ``tooz`` supports,
see `<http://docs.openstack.org/developer/tooz/drivers.html>`_.

To enable this feature, you must set the following in ``orchestrator.ini``::

    [coordination]
    enabled=True  # enable the feature
    url=kazoo://zookeeper.localnet:2181?timeout=5  # a URL to a tooz-supported coordination service
    group_id=astara.orchestrator # optional, change this if deploying multiple clusters
    heartbeat_interval=1 # optional, tune as needed
