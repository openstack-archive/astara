..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode


Title of your blueprint
=======================

Rug HA and scaleout

Problem Description
===================

The RUG is a multi-process, multi-worker service but it be cannot be
scaled out to multiple nodes for purposes of high-availability and
distributed handling of load.  The only currently option for a
highly-available is to do an active/passive cluster using Pacemaker
or similar, which is less than ideal and does not address scale-out
concerns.

Proposed Change
===============

This proposes allowing multiple RUG processes to be spawned across
many nodes.  Each RUG process is responsible for a fraction of the
total running appliances.  RUG_process->appliance(s) mapping will be
managed by a consistent hash ring.  An external coordination service
(ie, zookeeper) will be leveraged to provide cluster membership
capabilities, and python-tooz will be used to manage cluster events.
When new members join or depart, the hash ring will be rebalanced and
appliances re-distributed across the RUG.

This allows operators to scale out to many RUG instances, eliminating
the single-point-of-failure and allowing appliances to be evenly
distributed across multiple worker processes.


Data Model Impact
-----------------

n/a

REST API Impact
---------------

n/a

Security Impact
---------------

None

Notifications Impact
--------------------


Other End User Impact
---------------------

n/a

Performance Impact
------------------

There will be some new overhead introduced the messaging layer as Neutron
notifications and RPCs will need to be distributed to per-RUG message queues.

Other Deployer Impact
---------------------

Deployers will need to evaluate and choose an appropriate backend to be used
by tooz for leader election.  memcached is a simple yet non-robust solution,
while zookeeper is a less light-weight but proven one.  More info at [2]

Developer Impact
----------------

n/a

Community Impact
----------------

n/a


Alternatives
------------

One alternative to having each RUG instance declare its own messaging queue and
inspect all incoming messages would be to have the DHT master also serve as a
notification master. That is, the leader would be the only instance of the RUG
listening to and processing incoming Neutron notificatons, and then
re-distributing them to specific RUG workers based on the state of the DHT.

Another option would be to do away with the use of Neutron notifications
entirely and hard-wire the akanda-neutron plugin to the RUG via a dedicated
message queue.


Implementation
==============

This proposes enabling operators to run multiple instances of the RUG.
Each instance of the RUG will be responsible for a subset of the managed
appliances.  A distributed, consistent hash ring will be used to map appliances
to their respective RUG instance. The Ironic project is already doing
something similar and has a hashring implementation we can likely leverage
to get started [1]

The RUG cluster is essentially leaderless.  The hash ring is constructed
using the active node list and each indvidual RUG instance is capable of
constructing a ring given a list of members.  This ring is consistent
across nodes provided the coordination service is properly reporting membership
events and they are processed correctly.  Using metadata attached to incoming
events (ie, tenant_id), a consumer is able to check the hash ring to determine
which node in the ring the event is mapped to.

The RUG will spawn a new subprocess called the coordinator.  It's only purpose
is to listen for cluster membership events using python-tooz.  When a member
joins or departs, the coordinator will create a new Event of type REBALANCE
and put it onto the notifications queue.  This event's body will contain an
updated list of current cluster nodes.

Each RUG worker process will maintain a copy of the hash ring, which is
shared by its worker threads.  When it receives a REBALANCE event, it will
rebalance the hash ring given the new membership list.  When it receives
normal CRUD events for resources, it will first check the hash ring to see
if it is mapped to its host based on target tenant_id for the event. If it is,
the event will be processed. If it is not, the event will be ignored and
serviced by another worker.

Ideally, REBALANCE events should be serviced before CRUD events.

Assignee(s)
-----------


Work Items
----------

* Implement a distributed hash ring for managing worker:appliance
assignment

* Add new coordination sub-process to the RUG that publishes REBALANCE
events to the notifications queue when membership changes

* Setup per-RUG message queues such that notifications are distributed to all
RUG processes equally.

* Update worker to manage its own copy of the hash ring

* Update worker /w ability to respond to new REBALANCE events by rebalancing
the ring with an updated membership list

* Update worker to drop events for resources that are not mapped to its host in
the hash ring.

Dependencies
============

Testing
=======

Tempest Tests
-------------


Functional Tests
----------------

If we cannot sufficiently test this using unit tests, we could potentially
spin up our devstack job with multiple copies of the akanda-rug-service
running on a single host, and having multiple router appliances.  This
would allow us to test ring rebalancing by killing off one of the multiple
akanda-rug-service processes.

API Tests
---------


Documentation Impact
====================

User Documentation
------------------

Deployment docs need to be updated to mention this feature is dependent
on an external coordination service.

Developer Documentation
-----------------------


References
==========

[1] https://git.openstack.org/cgit/openstack/ironic/tree/ironic/common/hash_ring.py
[2] http://docs.openstack.org/developer/tooz/drivers.html

