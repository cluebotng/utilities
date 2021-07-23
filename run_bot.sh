#!/bin/bash
set -e

if [ -d '/data/project/cluebotng/apps/bot/bot' ];
then
  cd /data/project/cluebotng/apps/bot/bot
else
  cd /data/project/cluebotng/apps/bot
fi

/data/project/cluebotng/apps/utilities/update_node.sh bot
exec php -f cluebot-ng.php
