#!/bin/sh
# Daily PostgreSQL backup for the Compose "backup" service.
# Writes a compressed custom-format dump to $BACKUP_DIR, prunes dumps older than $BACKUP_KEEP_DAYS,
# then sleeps until the next run. Set BACKUP_ONCE=1 to take a single backup and exit.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
HOUR="${BACKUP_HOUR_UTC:-21}"   # 21:00 UTC = 02:30 IST next day, a quiet time for an Indian audience
HOST="${PGHOST:-postgres}"
DB="${POSTGRES_DB:-stataxis}"
USER_NAME="${POSTGRES_USER:-stataxis}"
export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

mkdir -p "$BACKUP_DIR"

backup_once() {
  stamp="$(date -u +%Y-%m-%d_%H%M%S)"
  tmp="$BACKUP_DIR/.stataxis-$stamp.dump.partial"
  final="$BACKUP_DIR/stataxis-$stamp.dump"
  if pg_dump -h "$HOST" -U "$USER_NAME" -d "$DB" --format=custom --compress=6 --file="$tmp"; then
    mv "$tmp" "$final"
    echo "backup ok: $final ($(du -h "$final" | cut -f1))"
    find "$BACKUP_DIR" -name 'stataxis-*.dump' -type f -mtime +"$KEEP_DAYS" -print -delete
  else
    rm -f "$tmp"
    echo "backup FAILED at $stamp" >&2
    return 1
  fi
}

if [ "${BACKUP_ONCE:-0}" = "1" ]; then
  backup_once
  exit $?
fi

while true; do
  now="$(date -u +%s)"
  today_run="$(date -u -d "$(date -u +%Y-%m-%d) $HOUR:00:00" +%s 2>/dev/null || echo 0)"
  if [ "$today_run" -le "$now" ]; then
    today_run=$((today_run + 86400))
  fi
  wait_s=$((today_run - now))
  echo "next backup in ${wait_s}s"
  sleep "$wait_s"
  backup_once || true   # a failed night must not kill the loop; the next night tries again
done
