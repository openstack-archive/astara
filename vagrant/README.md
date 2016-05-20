vagrant-devstack-astara
=======================

Getting started
---------------

A Vagrant based astara.

Steps to try vagrant image:

 1. Install Vagrant on your local machine. Install one of the current
    providers supported: VirtualBox, Libvirt or Vagrant
 2. Git clone the astara repository.
 3. Run `cd vagrant`
 4. Run `vagrant up`
    It will take from 10 to 60 minutes, depending on your internet speed.
    Vagrant-cachier can speed up the process [1].
 5. `vagrant ssh`
    You will get a VM with everything running.
    You will get vm shell with keystone and neutron already running.

At this point you should have astara running inside of the Vagrant VM.

[1] http://fgrehm.viewdocs.io/vagrant-cachier/

Vagrant Options available
-------------------------

You can set the following environment variables before running `vagrant up` to modify
the definition of the Virtual Machine spawned:

 * **VAGRANT\_ASTARA\_VM\_BOX**: To change the Vagrant Box used. Should be available in
   [atlas](http://atlas.hashicorp.com).

       export VAGRANT_ASTARA_VM_BOX=centos/7

   Could be an example of a rpm-based option.

 * **VAGRANT\_ASTARA\_VM\_MEMORY**: To modify the RAM of the VM. Defaulted to: 4096
 * **VAGRANT\_ASTARA\_VM\_CPU**: To modify the cpus of the VM. Defaulted to: 2
 * **VAGRANT\_ASTARA\_RUN\_DEVSTACK**: Whether `vagrant up` should run devstack to
   have an environment ready to use. Set it to 'false' if you want to edit
   `local.conf` before run ./stack.sh manually in the VM. Defaulted to: true.
   See below for additional options for editing local.conf.

Additional devstack configuration
---------------------------------

To add additional configuration to local.conf before the VM is provisioned, you can
create a file called "user_local.conf" in the vagrant directory of astara. This file
will be appended to the "local.conf" created during the Vagrant provisioning.

For example, to use OVN as the Neutron plugin with Astara, you can create a
"user_local.conf" with the following configuration:

    enable_plugin networking-ovn http://git.openstack.org/openstack/networking-ovn
    enable_service ovn-northd
    enable_service ovn-controller
    disable_service q-agt
    disable_service q-l3
