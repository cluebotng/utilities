#!/bin/bash
mkdir -p "$HOME/mysql_backups"
filename=`date +"%d-%m-%Y_%H-%M-%S"`

echo "Dumping the bot db"
mysqldump  --defaults-file="${HOME}"/replica.my.cnf -h tools.labsdb s52585__cb > "$HOME/mysql_backups/$filename-cb.sql"
