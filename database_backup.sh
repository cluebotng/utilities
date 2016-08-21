#!/bin/bash
if [ "$(whoami)" == "tools.cluebot" ];
then
    export DB_USER=s51109
fi
if [ "$(whoami)" == "tools.cluebotng" ];
then
    export DB_USER=s52585
fi
if [ "$(whoami)" == "tools.cluebotng-staging" ];
then
    export DB_USER=s53115
fi

if [ -z "$DB_USER" ];
then
    echo "I don't know what to do!"
    exit 1
fi

mkdir -p "$HOME/mysql_backups"
filename=`date +"%d-%m-%Y_%H-%M-%S"`

echo "Dumping the bot db"
mysqldump  --defaults-file="${HOME}"/replica.my.cnf -h tools-db $DB_USER"__cb" > "$HOME/mysql_backups/$filename-cb.sql"

echo "Dumping the interface db"
mysqldump  --defaults-file="${HOME}"/replica.my.cnf -h tools-db $DB_USER"__interface" > "$HOME/mysql_backups/$filename-interface.sql"
