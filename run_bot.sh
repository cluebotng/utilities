#!/bin/bash
set -e
cd /data/project/cluebotng/apps/bot

/data/project/cluebotng/apps/utilities/update_node.sh bot
exec php -f cluebot-ng.php
