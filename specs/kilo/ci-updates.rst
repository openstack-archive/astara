..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode


Title of your blueprint
=======================

Akanda CI updates for Kilo

Problem Description
===================

We build lots of interconnected things but dont test any of the things.  We
should be employing pre-commit testing similar to other projects to ensure
users get something thats not broken when deploying from master of git
repositories or generated tarballs and images.

Proposed Change
===============

All changes to Akanda projects should go through regular check and gate
phases that test a deployment containing proposed code changes. This
includes changes to Akanda code as well as supporting things like its devstack
code and ``akanda-appliance-builder``.  We can leverage devstack, tempest
and diskimage-builder to do this and create a generic Akanda integration
testing job that can be added to the pipelines of relevant projects. We should
also be running standard unit test coverage and pep8 checks here, too.

For code that runs in the Akanda appliance VM or code that is used to build
said image, we should ensure that tests run against proposed changes and not
static, pre-built appliance images.  That is, runs that are testing changes
to ``akanda-appliance`` should build and entirely new appliance VM image and
use that for its integration tests instead of pulling a pre-built image that
does not contain the code under review.

Additionally, we should be archiving the results of changes to these
appliance-related repositories as a 'latest' image. That is, if someone
lands a change to ``akanda-appliance``, we should build and archive a
VM image in a known location on the internet.  This will speed up other
tests that do not need to build a new image but should run against the
latest version, and also avoid forcing users to needlessly build images.

For changes that do not modify the appliance code or tooling used to build
the image, tests should run with a pre-built image. This can be either a
'latest' image or a released, versioned image.

One question at this point is where we run the Tempest jobs.  These usually
take between 30min-1hr to complete and the nodes that run them in the main
OpenStack gate are a limited resource. We may need to maintain our own third
party CI infrastructure to do this. TBD.

Data Model Impact
-----------------

None

REST API Impact
---------------

None

Security Impact
---------------

None

Notifications Impact
--------------------

None

Other End User Impact
---------------------

None

Performance Impact
------------------

None

Other Deployer Impact
---------------------

None

Developer Impact
----------------

Developers hoping to land code in any of the Akanda repositories will need to
ensure their code passes all gate tests before it can land.

Community Impact
----------------

This may make landing changes a bit slower but should improve the overall
quality and health of Akanda repositories.


Alternatives
------------


Implementation
==============

Assignee(s)
-----------


Work Items
----------

* Enable pep8 and unit test jobs against relevant Akanda repositories.

* Move existing devstack code to out of ``http://github.com/dreamhost/akanda-devstack.git``
  and into a proper gerrit-managed Akanda repository in the stackforge namespace.

* Complete diskimage-builder support that currently exists in
  ``http://github.com/stackforge/akanda-appliance-builder.git``

* Update devstack code to either pull a pre-built Akanda appliance image from a
  known URL or to build one from source for use in test run.

* Create a generic ``(check|gate)-dsvm-tempest-akanda`` job that spins up the
  Akanda devstack deployment and runs a subset of Tempest tests against it.

* Identifiy the subset of Tempest tests we care to run.

* Sync with openstack-infra and determine how and where these integration test
  jobs will run.

* Run the devstack job against changes to ``akanda-appliance`` or
  ``akanda-appliace-builder`` with a configuration such that the appliance
  image will be built from source including the patch under review.

* Setup infrastructure to publish a new appliance image
  (ie, akanda-appliance-latest.qcow2) to a known location on the internet
  after code lands in ``akanda-appliance`` or ``akanda-appliance-builder``

* Run the devstack job against all other relevant akanda repositories with a
  configuration such that a pre-built appliance image from a known location on
  the internet.  Ideally, this will be the image produced from changes to
  the appliance repositories (ie, akanda-appliance-latest.qcow2)

Dependencies
============

None

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

Should be updated to reflect the new home of devstack code and proper ways to
deploy it.

Developer Documentation
-----------------------

Should be updated to reflect the new home of devstack code and proper ways to
deploy it.

References
==========

None
