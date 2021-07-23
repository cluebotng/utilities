#!/bin/bash
set -e
cd /data/project/cluebotng/apps/core

/data/project/cluebotng/apps/utilities/update_node.sh core
exec ./cluebotng -l -m live_run
