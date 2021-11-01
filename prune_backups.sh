#!/bin/bash
set -e
echo "Removing backups older than 3 days"
find "$HOME/mysql_backups" -mtime +3 -delete
