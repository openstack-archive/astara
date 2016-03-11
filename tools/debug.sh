#!/bin/bash
echo "Post-test servers:"
nova list --all-tenants

for server in `nova list --all-tenants | grep ak | awk '{ print $2 }' | grep -v ID`; do
  echo "Post-test inspecting server $server"
  addr=`nova show $server | grep mgt | awk '{ print $5 }'`
  echo "Has address $addr"
  if ping6 -c3 $addr; then
    echo "API Test of server $server at addr $addr"
    curl -g http://[$addr]:5000/v1/system/interfaces
  else
    echo "Server $server unreachable at addr $addr!"
  fi
  echo "Console log for server $server"
  nova console-log $server
done

