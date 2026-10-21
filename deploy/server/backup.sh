#!/bin/sh
# Daily PostgreSQL dump into the mounted backup folder (the 10 TB disk).
set -eu
umask 077
keep="${BACKUP_KEEP_DAYS:-14}"
while true; do
	stamp=$(date -u +%Y%m%dT%H%M%SZ)
	file="/backups/bots-central-$stamp.dump"
	if pg_dump --format=custom --file="$file.partial"; then
		mv "$file.partial" "$file"
		echo "backup ok: $file"
	else
		rm -f "$file.partial"
		echo "backup FAILED" >&2
	fi
	find /backups -name 'bots-central-*.dump' -type f -mtime "+$keep" -delete
	sleep 86400
done
