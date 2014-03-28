======================
 Worker State Machine
======================

.. graphviz:: state_machine.dot

States
======

:CALC_ACTION: Coalesces the pending actions from the queue inside the state machine.
:ALIVE: Checks whether the instance is alive.
:STATS: Reads traffic data from the router.
:CREATE: Makes a new VM instance.
:CHECKBOOT: Check if a new VM instance has been booted and initially configured.
:CONFIG: Configures the VM and its services.
:STOP: Terminates a running VM.
:EXIT: Processing stops.

ACT(ion) Variable
=================

:Create: Create router was requested.
:Read: Read router traffic stats.
:Update: Update router configuration.
:Delete: Delete router.
:Poll: Poll router alive status.

vm Variable
===========

:Down: VM is known to be down.
:Booting: VM is booting.
:Up: VM is known to be up (pingable).
:Configured: VM is known to be configured.
:Restart Needed: VM needs to be rebooted.
