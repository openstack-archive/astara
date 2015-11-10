..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode


Title of your blueprint
=======================

Liberty release documentation updates


Problem Description
===================

The documentation needs to be easy for new users and contributors while
following similar OpenStack docs structure and conventions.


Proposed Change
===============

Organize the documentation around four sections: What Is Akanda, Installing
Akanda, Operating Akanda, and Akanda Developer Guide.

This change will make the Akanda documentation [1] read similar to the existing
OpenStack documentation [2]. This will also prepare the Akanda documentation
for merging with the OpenStack documentation.

What Is Akanda section will hold the existing High Level Architecture,
Service VM Orchestration and Management, The Service VM sections. These pages
VM will be renamed to Instance. We will
add user documentation for demonstrating akanda, understanding how it
orchestrates network services, and how to compare (or not to) akanda to other
SDN options. Add some details around EW and NS frame/packet flow between
compute nodes. Make IPv6 support very clear and called out. Explain the driver
concept and how it will make support of new Neutron Advanced services easier.
Additionally provide understanding of how Akanda integrates with Neutron. Say
all this without duplicating any of the existing OpenStack documentation.

Installing Akanda section will hold the existing Akanda Developer Quickstart.
Adding installing from tarballs, source, and eventually distribution. Known good
configurations will also be part of this section.

Operating Akanda will hold the existing Operation and Deployment and
Configuration Options. We will add the training material here. We will need to
add details on dynamic routing support, how the configuration drift support
works and is managed. Links to supporting ML2 drivers like linuxbridge and OVS.
Making it clear how Akanda supports common Neutron configurations and
configuration changes. Add details on supporting VXLAN overlay and Lightweight
Network Virtualization (LNV) (Hierarchical Port Binding) with Akanda.

Akanda Developer Guide will hold the details on setting up the developer
environment, testing code locally, explaining the CI tests, along with some
references to Neutron dependencies. This entire section will move to the
Akanda developer reference section here [3], once the Akanda project is
accepted into the OpenStack org repo.

This spec also includes the use of docstrings in the code. We will start with
updating the rug code with docstrings as the most critical.


Data Model Impact
-----------------

n/a


REST API Impact
---------------

n/a


Security Impact
---------------

n/a


Notifications Impact
--------------------

n/a


Other End User Impact
---------------------

n/a


Performance Impact
------------------

n/a


Other Deployer Impact
---------------------

n/a


Developer Impact
----------------

Updating the documentation structure will make it easier for new contributors
to join the Akanda project. As Akanda joins the OpenStack org repo structure,
it will make setting up the devref material very easy.


Community Impact
----------------

The OpenStack community will better understand what the Akanda project is
about and why it is important with clear documentation.


Alternatives
------------

* Leave documentation as is
* Wait until the Akanda project is moved into the OpenStack org repo before
updating the documentation structure.


Implementation
==============

Assignee(s)
-----------

Sean Roberts (sarob)


Work Items
----------

* Create a patch to restructure the Akanda documentation
* Add new content from slides and other sources
* After Akanda gets moved into OpenStack org repos, move the Akanda developer
reference to doc.openstack.org/developer/akanda/devref/


Dependencies
============


Testing
=======

Tempest Tests
-------------

n/a


Functional Tests
----------------

n/a


API Tests
---------

n/a


Documentation Impact
====================

User Documentation
------------------

See the proposed change section


Developer Documentation
-----------------------

See the proposed change section


References
==========

[1] http://docs.akanda.io/
[2] http://docs.openstack.org/
[3] http://docs.openstack.org/developer/openstack-projects.html
