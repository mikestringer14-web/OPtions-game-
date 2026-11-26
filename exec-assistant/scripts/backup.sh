#!/bin/sh
# Nightly: consistent SQLite snapshot -> encrypted with your age public key -> keep 30 days.
# Restore: age -d -i your-key.txt assistant-YYYY-MM-DD.db.age > assistant.db
set -eu
apk add --no-cache age sqlite >/dev/null
while true; do
  stamp=$(date +%F)
  sqlite3 /data/assistant.db ".backup /tmp/snapshot.db"
  age -R /age-recipient.txt -o "/backups/assistant-${stamp}.db.age" /tmp/snapshot.db
  shred -u /tmp/snapshot.db 2>/dev/null || true
  find /backups -name 'assistant-*.db.age' -mtime +30 -exec rm -f {} \;
  sleep 86400
done
