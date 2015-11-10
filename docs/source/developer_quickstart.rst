.. _developer_quickstart:

Akanda Developer Quickstart
=====================================

This guide provides guidance for new developers looking to get up and running
with an Akanda development environment. The Akanda components may be easily
deployed alongside OpenStack using DevStack. For more information about
DevStack visit ``http://docs.openstack.org/developer/devstack/``.


.. _developer_quickstart_rest:

Deploying Akanda using DevStack
-------------------------------

Preparation and prerequisites
+++++++++++++++++++++++++++++

Deploying DevStack on your local workstation is not recommended. Instead,
developers should use a dedicated virtual machine.  Currently, Ubuntu
Trusty 14.04 is the tested and supported base operating system. Additionally,
you'll need at least 4GB of RAM and to have ``git`` installed::

    sudo apt-get -y install git


First clone the DevStack repository::

    sudo mkdir -p /opt/stack/
    sudo chown `whoami` /opt/stack
    git clone https://git.openstack.org/openstack-dev/devstack /opt/stack/devstack


Configuring DevStack
++++++++++++++++++++

Next, you will need to enable the Akanda plugin in the DevStack configuration
and enable the relevant services::

    cat >/opt/stack/devstack/local.conf <<END
    [[local|localrc]]
    enable_plugin akanda-rug https://github.com/stackforge/akanda-rug
    enable_service q-svc q-agt ak-rug
    disable_service n-net

    HOST_IP=127.0.0.1
    LOGFILE=/opt/stack/devstack/devstack.log
    DATABASE_PASSWORD=secret
    RABBIT_PASSWORD=secret
    SERVICE_TOKEN=secret
    SERVICE_PASSWORD=secret
    ADMIN_PASSWORD=secret
    END

You may wish to SSH into the appliance VMs for debugging purposes. The RUG will
enable access for the 'akanda' user for a specified public key.  This may be
specified by setting AKANDA_APPLIANCE_SSH_PUBLIC_KEY variable in your devstack
config to point to an existing public key.  The default is
$HOME/.ssh/id_rsa.pub.

Building a Custom Service VM
++++++++++++++++++++++++++++

By default, the Akanda plugin downloads a pre-built official Akanda image.  To
build your own from source, enable ``BUILD_AKANDA_APPLIANCE_IMAGE`` and specify
a repository and branch to build from::

    cat >>/opt/stack/devstack/local.conf <<END

    BUILD_AKANDA_APPLIANCE_IMAGE=True
    AKANDA_APPLIANCE_REPO=http://github.com/stackforge/akanda-appliance.git
    AKANDA_APPLIANCE_BRANCH=master
    END

To build the appliance using locally modified ``akanda-appliance`` code, you
may point devstack at the local git checkout by setting the
AKANDA_APPLIANCE_DIR variable.  Ensure that any changes you want included in
the image build have been committed to the repository and it is checked out
to the proper commit.

Deploying
+++++++++

Simply run DevStack and allow time for the deployment to complete::

    cd /opt/stack/devstack
    ./stack.sh

After it has completed, you should have a ``akanda-rug`` process running
alongside the other services and an Akanda router appliance booted as a Nova
instance.
