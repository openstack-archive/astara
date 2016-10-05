This directory contains the astara devstack plugin for Kilo and beyond. You
will need to enable the plugin in your local.conf file by adding the
following to the [[local|localrc]] section.

    enable_plugin astara <GITURL> [GITREF]

For example:

    enable_plugin astara http://github.com/openstack/astara

For more info see: http://docs.openstack.org/developer/devstack/plugins.html
