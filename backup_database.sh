#!/bin/bash
set -e
mkdir -p "$HOME/mysql_backups"

mysqldump \
  --defaults-file="${HOME}"/replica.my.cnf \
  -h tools-db \
  s52585__cb > "$HOME/mysql_backups/$(date +"%d-%m-%Y_%H-%M-%S")-cb.sql"
