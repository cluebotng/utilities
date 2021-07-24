#!/bin/bash
set -e
cd /data/project/cluebotng/apps/irc_relay

/data/project/cluebotng/apps/utilities/update_node.sh irc_relay
exec ./relay.py
