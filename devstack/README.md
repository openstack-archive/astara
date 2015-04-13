This directory contains the akanda-rug devstack plugin for Kilo and beyond. You
will need to enable the plugin in your local.conf file by adding the
following to the [[local|localrc]] section.

    enable_plugin akanda-rug <GITURL> [GITREF]

For example:

    enable_plugin akanda-rug http://github.com/akanda/akanda-rug stable/kilo

You will also need to enable the service:

    enable_service ak-rug

For more info see: http://docs.openstack.org/developer/devstack/plugins.html
