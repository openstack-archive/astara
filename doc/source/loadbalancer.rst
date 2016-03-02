
Install an Astara Load Balancer
===============================

How to configure Astara to be able to create load balancers
-----------------------------------------------------------

In this example we will create an image that can be used for both a router or a loadbalancer. Then we will configure both astara and neutron for loadbalancer support, which will use the lbaasV2 commands. We can then use the lbaasV2 commands to create a loadbalancer.

Build loadbalancer applicance image:
-------------------------------------

1. Build an image to include loadbalancer support by using one of the two following commands. If you have a license for nginx plus you will be able to take advantage of some of these nginx-plus features but you must first copy over your nginx certs. Run this commad in the astara-appliance directory::

    ELEMENTS_PATH=diskimage-builder/elements DIB_RELEASE=jessie DIB_EXTLINUX=1 \
    DIB_ASTARA_ADVANCED_SERVICES=router,loadbalancer disk-image-create debian vm astara nginx -o astara-lb

or for nginx plus: (nginx certs will need to be copied ove before running this command). Run this commad in the astara-appliance directory::

    ELEMENTS_PATH=diskimage-builder/elements DIB_RELEASE=jessie DIB_EXTLINUX=1 \
    DIB_ASTARA_ADVANCED_SERVICES=router,loadbalancer disk-image-create debian vm astara nginx-plus -o astara-lb

Configure Neutron for Astara loadbalancer support
-------------------------------------------------

1. Make the following changes to neutron.conf
  in the [DEFAULT] section::

    core_plugin = astara_neutron.plugins.ml2_neutron_plugin.Ml2Plugin
    service_plugins = astara_neutron.plugins.ml2_neutron_plugin.L3RouterPlugin,astara_neutron.plugins.lbaas_neutron_plugin.LoadBalancerPluginv2
    api_extensions_path = /usr/local/lib/python2.7/dist-packages/astara_neutron/extensions:/usr/local/lib/python2.7/dist-packages/neutron_lbaas/extensions

  in the [SERVICE_PROVIDERS] section (you may have to add this section if it doesn't exist)::

    service_provider = LOADBALANCERV2:LoggingNoop:neutron_lbaas.drivers.logging_noop.driver.LoggingNoopLoadBalancerDriver:default


2. Create the loadbalancer tables in the neutron database::

    neutron-db-manage --service lbaas upgrade head

Configure Astara for loadbalancer support
-----------------------------------------

1. Make the following changes to orchestrator.conf.

  in the [DEFAULT] section::

    enabled_drivers = router,loadbalancer

  in the [LOADBALANCER] section::

    image_uuid = <loadbalancer image ID>
    instance_flavor = 6

  (If you are using this image for the router also, in the [ROUTER] section, set the image_uuid to this value also.)

2. Restart the neutron-server and astara services to pick up the changes::

    restart neutron-server
    restart astara

Create a loadbalancer
---------------------

1. Build a loadbalancer (this assumes that you have two web servers at ips -WEB1_IP, WEB2_IP which will used in the following commands)::

    neutron lbaas-loadbalancer-create --name lb1 private-subnet
    neutron lbaas-loadbalancer-show lb1 # Note the VIP address
    neutron lbaas-listener-create --loadbalancer lb1 --protocol HTTP --protocol-port 80 --name listener1
    neutron lbaas-pool-create --lb-algorithm ROUND_ROBIN --listener listener1 --protocol HTTP --name pool1
    neutron lbaas-member-create  --subnet private-subnet --address 10.2.0.4 --protocol-port 80 --name mem1 pool1
    neutron lbaas-member-create  --subnet private-subnet --address 10.2.0.5 --protocol-port 80 --name mem2 pool1
    neutron lbaas-healthmonitor-create --delay 3 --type HTTP  --max-retries 3 --timeout 3 --pool pool1 --name hm1

2. Once finished you can delete everything using the following::

    neutron lbaas-member-delete mem1 pool1
    neutron lbaas-member-delete mem2 pool1
    neutron lbaas-pool-delete pool1
    neutron lbaas-listener-delete listener1
    neutron lbaas-loadbalancer-delete lb1

