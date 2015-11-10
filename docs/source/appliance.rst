.. _appliance:

The Service VM (the Akanda Appliance)
=====================================

Akanda uses Linux-based images (stored in OpenStack Glance) to provide layer
3 routing and advanced networking services.  Akanda, Inc provides stable image
releases for download at `akanda.io <http://akanda.io>`_, but it's also
possible to build your own custom Service VM image (running additional
services of your own on top of the routing and other default services provided
by Akanda).

.. _appliance_build:

Building a Service VM image from source
---------------------------------------

The router code that runs within the appliance is hosted in the ``akanda-appliance``
repository at ``https://github.com/stackforge/akanda-appliance``.  Additional tooling
for actually building a VM image to run the appliance is located in that repository's
``disk-image-builder`` sub-directory, in the form elements to be used with
``diskimage-builder``.  The following instructions will walk through
building the Debian-based appliance locally, publishing to Glance and configuring the RUG to
use said image. These instructions are for building the image on an Ubuntu 14.04+ system.

Install Prerequisites
+++++++++++++++++++++

First, install ``diskimage-builder`` and required packages:

::

    sudo apt-get -y install debootstrap qemu-utils
    sudo pip install "diskimage-builder<0.1.43"

Next, clone the ``akanda-appliance-builder`` repository:

::

    git clone https://github.com/stackforge/akanda-appliance


Build the image
+++++++++++++++

Kick off an image build using diskimage-builder:

::

    cd akanda-appliance
    ELEMENTS_PATH=diskimage-builder/elements DIB_RELEASE=wheezy DIB_EXTLINUX=1 \
    disk-image-create debian vm akanda -o akanda

Publish the image
+++++++++++++++++

The previous step should produce a qcow2 image called ``akanda.qcow`` that can be
published into Glance for use by the system:

::

    # We assume you have the required OpenStack credentials set as an environment
    # variables
    glance image-create --name akanda --disk-format qcow2 --container-format bare \
        --file akanda.qcow2
    +------------------+--------------------------------------+
    | Property         | Value                                |
    +------------------+--------------------------------------+
    | checksum         | cfc24b67e262719199c2c4dfccb6c808     |
    | container_format | bare                                 |
    | created_at       | 2015-05-13T21:27:02.000000           |
    | deleted          | False                                |
    | deleted_at       | None                                 |
    | disk_format      | qcow2                                |
    | id               | e2caf7fa-9b51-4f42-9fb9-8cfce96aad5a |
    | is_public        | False                                |
    | min_disk         | 0                                    |
    | min_ram          | 0                                    |
    | name             | akanda                               |
    | owner            | df8eaa19c1d44365911902e738c2b10a     |
    | protected        | False                                |
    | size             | 450573824                            |
    | status           | active                               |
    | updated_at       | 2015-05-13T21:27:03.000000           |
    | virtual_size     | None                                 |
    +------------------+--------------------------------------+

Configure the RUG
+++++++++++++++++

Take the above image id and set the corresponding value in the RUG's config file, to instruct
the service to use that image for software router instances it manages:

::

    vi /etc/akanda/rug.ini
    ...
    router_image_uuid=e2caf7fa-9b51-4f42-9fb9-8cfce96aad5a

Making local changes to the appliance service
+++++++++++++++++++++++++++++++++++++++++++++

By default, building an image in this way pulls the ``akanda-appliance`` code directly
from the upstream tip of trunk.  If you'd like to make modifications to this code locally
and build an image containing those changes, set DIB_REPOLOCATION_akanda and DIB_REPOREF_akanda
in your enviornment accordingly during the image build, ie:

::

    export DIB_REPOLOCATION_akanda=~/src/akanda-appliance  # Location of the local repository checkout
    export DIB_REPOREF_akanda=my-new-feature # The branch name or SHA-1 hash of the git ref to build from.

.. _appliance_rest:

REST API
--------
The Akanda Appliance REST API is used by the :ref:`rug` service to manage
health and configuration of services on the router.

Router Health
+++++++++++++

``HTTP GET /v1/status/``
~~~~~~~~~~~~~~~~~~~~~~~~

Used to confirm that a router is responsive and has external network connectivity.

::

    Example HTTP 200 Response

    Content-Type: application/json
    {
        'v4': true,
        'v6': false,
    }

Router Configuration
++++++++++++++++++++

``HTTP GET /v1/firewall/rules/``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Used to retrieve an overview of configured firewall rules for the router (from
``iptables -L`` and ``iptables6 -L``).

::

    Example HTTP 200 Response

    Content-Type: text/plain
    Chain INPUT (policy DROP)
    target     prot opt source               destination
    ACCEPT     all  --  0.0.0.0/0            0.0.0.0/0
    ACCEPT     icmp --  0.0.0.0/0            0.0.0.0/0            icmptype 8

    ...


``HTTP GET /v1/system/interface/<ifname>/``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Used to retrieve JSON data about a specific interface on the router.

::

    Example HTTP 200 Response

    Content-Type: application/json
    {
        "interface": {
            "addresses": [
                "8.8.8.8",
                "2001:4860:4860::8888",
            ],
            "description": "",
            "groups": [],
            "ifname": "ge0",
            "lladdr": "fa:16:3f:de:21:e9",
            "media": null,
            "mtu": 1500,
            "state": "up"
        }
    }

``HTTP GET /v1/system/interfaces``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Used to retrieve JSON data about a `every` interface on the router.

::

    Example HTTP 200 Response

    Content-Type: application/json
    {
        "interfaces": [{
            "addresses": [
                "8.8.8.8",
                "2001:4860:4860::8888",
            ],
            "description": "",
            "groups": [],
            "ifname": "ge0",
            "lladdr": "fa:16:3f:de:21:e9",
            "media": null,
            "mtu": 1500,
            "state": "up"
        }, {
            ...
        }]
    }

``HTTP PUT /v1/system/config/``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Used (generally, by :program:`akanda-rug-service`) to push a new configuration
to the router and restart services as necessary:

::

    Example HTTP PUT Body

    Content-Type: application/json
    {
        "configuration": {
            "networks": [
                {
                    "address_allocations": [],
                    "interface": {
                        "addresses": [
                            "8.8.8.8",
                            "2001:4860:4860::8888"
                        ],
                        "description": "",
                        "groups": [],
                        "ifname": "ge1",
                        "lladdr": null,
                        "media": null,
                        "mtu": 1500,
                        "state": "up"
                    },
                    "name": "",
                    "network_id": "f0f8c937-9fb7-4a58-b83f-57e9515e36cb",
                    "network_type": "external",
                    "v4_conf_service": "static",
                    "v6_conf_service": "static"
                },
                {
                    "address_allocations": [],
                    "interface": {
                        "addresses": [
                            "..."
                        ],
                        "description": "",
                        "groups": [],
                        "ifname": "ge0",
                        "lladdr": "fa:16:f8:90:32:e3",
                        "media": null,
                        "mtu": 1500,
                        "state": "up"
                    },
                    "name": "",
                    "network_id": "15016de1-494b-4c65-97fb-475b40acf7e1",
                    "network_type": "management",
                    "v4_conf_service": "static",
                    "v6_conf_service": "static"
                },
                {
                    "address_allocations": [
                        {
                            "device_id": "7c400585-1743-42ca-a2a3-6b30dd34f83b",
                            "hostname": "10-10-10-1.local",
                            "ip_addresses": {
                                "10.10.10.1": true,
                                "2607:f298:6050:f0ff::1": false
                            },
                            "mac_address": "fa:16:4d:c3:95:81"
                        }
                    ],
                    "interface": {
                        "addresses": [
                            "10.10.10.1/24",
                            "2607:f298:6050:f0ff::1/64"
                        ],
                        "description": "",
                        "groups": [],
                        "ifname": "ge2",
                        "lladdr": null,
                        "media": null,
                        "mtu": 1500,
                        "state": "up"
                    },
                    "name": "",
                    "network_id": "31a242a0-95aa-49cd-b2db-cc00f33dfe88",
                    "network_type": "internal",
                    "v4_conf_service": "static",
                    "v6_conf_service": "static"
                }
            ],
            "static_routes": []
        }
    }

Survey of Software and Services
-------------------------------
The Akanda Appliance uses a variety of software and services to manage routing
and advanced services, such as:

    * ``iproute2`` tools (e.g., ``ip neigh``, ``ip addr``, ``ip route``, etc...)
    * ``dnsmasq``
    * ``bird6``
    * ``iptables`` and ``iptables6``

In addition, the Akanda Appliance includes two Python-based services:

    * The REST API (which :program:`akanda-rug-service)` communicates with to
      orchestrate router updates), deployed behind `gunicorn
      <http://gunicorn.org>`_.
    * A Python-based metadata proxy.

Proxying Instance Metadata
--------------------------

When OpenStack VMs boot with ``cloud-init``, they look for metadata on a
well-known address, ``169.254.169.254``.  To facilitate this process, Akanda
sets up a special NAT rule (one for each local network)::

    -A PREROUTING -i eth2 -d 169.254.169.254 -p tcp -m tcp --dport 80 -j DNAT --to-destination 10.10.10.1:9602

...and a special rule to allow metadata requests to pass across the management
network (where OpenStack Nova is running, and will answer requests)::

    -A INPUT -i !eth0 -d <management-v6-address-of-router> -j DROP

A Python-based metadata proxy runs locally on the router (in this example,
listening on ``http://10.10.10.1:9602``) and proxies these metadata requests
over the management network so that instances on local tenant networks will
have access to server metadata.
