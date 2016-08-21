#!/bin/bash
echo "Removing backups older than 7 days"
find "$HOME/mysql_backups" -mtime +7 -delete