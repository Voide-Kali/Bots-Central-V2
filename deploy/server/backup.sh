#!/bin/sh
# Daily PostgreSQL dump into the mounted backup folder, ENCRYPTED with age (ADR-033).
#
# Why encrypted: a dump includes command_payloads (bytes of files sent by the agent), so a plaintext
# copy keeps files around even after they are deleted from the database. The dump is encrypted to an
# age recipient (public key) whose PRIVATE key is kept OFF this server, so someone who copies the
# backup disk cannot read it. Restore needs that private key (see restore-backup.sh).
set -eu
umask 077
keep="${BACKUP_KEEP_DAYS:-14}"
: "${BACKUP_AGE_RECIPIENT:?defina BACKUP_AGE_RECIPIENT (chave publica age1... ) no .env — ver ADR-033}"

# One-time heads-up: pre-encryption plaintext dumps still on disk should be securely removed by hand
# (they are not auto-deleted, to avoid destroying the only copy before an encrypted one exists).
if ls /backups/bots-central-*.dump >/dev/null 2>&1; then
	echo "AVISO: existem dumps .dump em texto claro de antes da cifragem. Apague-os com seguranca" >&2
	echo "       (ex.: shred -u /backups/bots-central-*.dump) depois de confirmar um backup .age bom." >&2
fi

while true; do
	stamp=$(date -u +%Y%m%dT%H%M%SZ)
	file="/backups/bots-central-$stamp.dump.age"
	# pg_dump (custom format) para stdout, cifrado para o destinatario age antes de tocar o disco.
	if pg_dump --format=custom | age -r "$BACKUP_AGE_RECIPIENT" -o "$file.partial"; then
		mv "$file.partial" "$file"
		echo "backup ok: $file"
	else
		rm -f "$file.partial"
		echo "backup FAILED" >&2
	fi
	find /backups -name 'bots-central-*.dump.age' -type f -mtime "+$keep" -delete
	sleep 86400
done
