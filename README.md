# Astara

A service with an open plugin architecture that manages Neutron advanced
services such as routers and load balancers within an OpenStack environment.

## The Name

Astara is the sanskrit word for carpet. So why name our project carpet?

The original code name for this project was simply "The RUG" which was a
reference to a line from the popular film "The Big Lebowski":

**That rug really tied the room together, did it not?**

The idea is that "The Rug" really ties OpenStack neutron together nicely. We
felt it was an apt description so we kept the name.

## Related Projects

The code for the Astara project lives in several separate repositories to ease
packaging and management:


  * [Astara](https://github.com/openstack/astara) -
    Contains the Orchestration service for managing the creation, configuration,
    and health of neutron advanced services as virtual network functions.

  * [Astara Appliance](https://github.com/openstack/astara-appliance) –
    Supporting software for the Astara virtual network appliance, which is
    a Linux-based service VM that provides routing and L3+ services in
    a virtualized network environment. This includes a REST API for managing
    the appliance via the Astara orchestration service.

  * [Astara Neutron](https://github.com/openstack/astara-neutron) – 
    Ancillary subclasses of several OpenStack Neutron plugins and supporting
    code.

  * [Astara Horizon](https://github.com/openstack/astara-horizon) -
    OpenStack Horizon Dashboard code.


## Project Details

Astara is publicly managed through the [Astara Launchpad project](https://launchpad.net/astara)


## Code Review

The code goes to get reviewed by collaborators and merged at
[OpenStack Gerrit review](https://review.openstack.org)


## Documentation

Can be found at [docs.akanda.io](http://docs.akanda.io)

Developer quick start guides for making this all work in Devstack `Here
<docs/source/developer_quickstart.rst>`_


## Community

Talk to the developers through IRC [#openstack-astara channel on freenode.net]
(http://webchat.freenode.net/?randomnick=1&channels=%23openstack-astara&prompt=1&uio=d4)


## License and Copyright

Astara is licensed under the Apache-2.0 license and is Copyright 2015,
OpenStack Foundation
