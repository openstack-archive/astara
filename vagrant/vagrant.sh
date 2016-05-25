#!/bin/sh

export OS_USER=vagrant
export OS_HOST_IP=172.68.5.10

# run script
bash /vagrant/devstack.sh "$1"
