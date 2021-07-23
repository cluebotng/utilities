#!/bin/bash
set -e
cd /data/project/cluebotng/apps/core/current

/data/project/cluebotng/apps/utilities/update_node.sh core
exec ./cluebotng -l -m live_run
