#!/bin/bash
node=$(hostname -f | sed 's/[^A-Za-z0-9\._\-]+//g' | sed 's/"//g')
component=$(echo "$1" | sed 's/"//g')

if [ -z "$node" ] || [ -z "$component" ];
then
  echo "Usage $0 <component>";
  exit 1;
fi

exec mysql \
  --defaults-file="${HOME}"/replica.my.cnf \
  -h tools-db \
  s52585__cb \
  -e 'replace into `cluster_node` values ("'${node}'", "'${component}'")'
