======================
 Worker State Machine
======================

.. graphviz:: state_machine.dot

States
======

:CALC_ACTION: Coalesces the pending actions from the queue inside the state machine.
:ALIVE: Checks whether the instance is alive.
:CLEAR_ERROR: Clear the error status before attempting any further operation.
:STATS: Reads traffic data from the router.
:CREATE_VM: Makes a new VM instance.
:CHECKBOOT: Check if a new VM instance has been booted and initially configured.
:CONFIG: Configures the VM and its services.
:STOP_VM: Terminates a running VM.
:EXIT: Processing stops.

ACT(ion) Variable
=================

:Create: Create router was requested.
:Read: Read router traffic stats.
:Update: Update router configuration.
:Delete: Delete router.
:Poll: Poll router alive status.
:rEbuild: Recreate a router from scratch.

vm Variable
===========

:Down: VM is known to be down.
:Booting: VM is booting.
:Up: VM is known to be up (pingable).
:Configured: VM is known to be configured.
:Restart Needed: VM needs to be rebooted.
:Gone: The router definition has been removed from neutron.
:Error: The router has been rebooted too many times, or has had some
        other error.
