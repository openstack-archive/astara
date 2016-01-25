.. _developer_quickstart:

Astara Developer Quickstart
===========================

This guide provides guidance for new developers looking to get up and running
with an Astara development environment. The Astara components may be easily
deployed alongside OpenStack using DevStack. For more information about
DevStack visit ``http://docs.openstack.org/developer/devstack/``.


.. _developer_quickstart_rest:

Deploying Astara using DevStack
-------------------------------

Preparation and prerequisites
+++++++++++++++++++++++++++++

Deploying DevStack on your local workstation is not recommended. Instead,
developers should use a dedicated virtual machine.  Currently, Ubuntu
Trusty 14.04 is the tested and supported base operating system. Additionally,
you'll need at least 4GB of RAM (8 is better) and to have ``git`` installed::

    sudo apt-get -y install git


First clone the DevStack repository::

    sudo mkdir -p /opt/stack/
    sudo chown `whoami` /opt/stack
    git clone https://git.openstack.org/openstack-dev/devstack /opt/stack/devstack


Configuring DevStack
++++++++++++++++++++

Next, you will need to enable the Astara plugin in the DevStack configuration
and enable the relevant services::

    cat >/opt/stack/devstack/local.conf <<END
    [[local|localrc]]
    enable_plugin astara https://github.com/openstack/astara
    enable_service q-svc q-agt astara
    disable_service n-net

    HOST_IP=127.0.0.1
    LOGFILE=/opt/stack/logs/devstack.log
    DATABASE_PASSWORD=secret
    RABBIT_PASSWORD=secret
    SERVICE_TOKEN=secret
    SERVICE_PASSWORD=secret
    ADMIN_PASSWORD=secret
    END

You may wish to SSH into the appliance VMs for debugging purposes. The
orchestrator will enable access for the 'astara' user for a specified public
key. This may be specified by setting ASTARA_APPLIANCE_SSH_PUBLIC_KEY variable
in your devstack config to point to an existing public key.  The default is
$HOME/.ssh/id_rsa.pub.

Building a Custom Service VM
++++++++++++++++++++++++++++

By default, the Astara plugin downloads a pre-built official Astara image.  To
build your own from source, enable ``BUILD_ASTARA_APPLIANCE_IMAGE`` and specify
a repository and branch to build from::

    cat >>/opt/stack/devstack/local.conf <<END

    BUILD_ASTARA_APPLIANCE_IMAGE=True
    ASTARA_APPLIANCE_REPO=http://github.com/openstack/astara-appliance.git
    ASTARA_APPLIANCE_BRANCH=master
    END

To build the appliance using locally modified ``astara-appliance`` code, you
may point devstack at the local git checkout by setting the
ASTARA_APPLIANCE_DIR variable.  Ensure that any changes you want included in
the image build have been committed to the repository and it is checked out
to the proper commit.

Deploying
+++++++++

Simply run DevStack and allow time for the deployment to complete::

    cd /opt/stack/devstack
    ./stack.sh

After it has completed, you should have a ``astara_orchestrator`` process running
alongside the other services and an Astara router appliance booted as a Nova
instance.
