#!/bin/bash
#
# Codabench backup — PostgreSQL dump + MinIO object store
#
# Creates, under BACKUP_ROOT:
#   YYYY_MM_DD_postgres_backup.sql.gz   every run (it is small)           -> kept RETENTION_DAYS_DB days
#   YYYY_MM_DD_minio_backup.tar.gz      once a week, or when none exists   -> the newest MINIO_KEEP are kept
#
# The object store archive is big (as large as var/minio) and rarely changes, so it is NOT taken every day: on a small
# disk, daily copies fill it in a few days. It is also skipped (with a WARNING and exit code 3) when there is not
# enough free space for it, instead of filling the disk.
#
# Install:
#   sudo cp codabench-backup.sh /usr/local/bin/codabench-backup
#   sudo chmod +x /usr/local/bin/codabench-backup
#   sudo /usr/local/bin/codabench-backup          # test run
#
# Take both backups right now (for example before an update), whatever the day:
#   sudo FORCE_MINIO_BACKUP=1 /usr/local/bin/codabench-backup
#
# Schedule (daily at 03:00):
#   sudo crontab -e
#   0 3 * * * /bin/bash /usr/local/bin/codabench-backup >> /var/log/codabench-backup.log 2>&1
#
# Every setting below can be overridden from the environment.
#
set -euo pipefail

# ---- Configuration ---------------------------------------------------------
CODABENCH_DIR="${CODABENCH_DIR:-/home/didimitrov/codabench-su}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/codabench}"

# Database dumps are tiny: keep a month of them
RETENTION_DAYS_DB="${RETENTION_DAYS_DB:-30}"
# Object store archives are big: keep only the newest ones
MINIO_KEEP="${MINIO_KEEP:-2}"
# Day of the week for the object store archive (1 = Monday ... 7 = Sunday)
MINIO_BACKUP_DAY="${MINIO_BACKUP_DAY:-7}"
# Take the object store archive today even if it is not its day (1 = yes)
FORCE_MINIO_BACKUP="${FORCE_MINIO_BACKUP:-0}"
# Free space (MB) that must remain after the archive is written, otherwise it is skipped
MIN_FREE_MB="${MIN_FREE_MB:-2048}"

# Set to 1 to enable maintenance mode during the backup. This makes the
# database dump and the MinIO archive consistent with each other, at the cost
# of a short outage. Recommended once you have real users.
USE_MAINTENANCE_MODE="${USE_MAINTENANCE_MODE:-0}"

# ---- Derived ---------------------------------------------------------------
DATE_STAMP="$(date +%Y_%m_%d)"
PG_OUT="${BACKUP_ROOT}/${DATE_STAMP}_postgres_backup.sql.gz"
MINIO_OUT="${BACKUP_ROOT}/${DATE_STAMP}_minio_backup.tar.gz"
MAINT_FLAG="${CODABENCH_DIR}/maintenance_mode/maintenance.on"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { log "ERROR: $*" >&2; exit 1; }

# ---- Read DB credentials from .env ----------------------------------------
[ -d "$CODABENCH_DIR" ] || die "Codabench directory not found: $CODABENCH_DIR (set CODABENCH_DIR)"
cd "$CODABENCH_DIR"
[ -f .env ] || die ".env not found in $CODABENCH_DIR"

get_env() {
    grep -E "^${1}=" .env | tail -1 | cut -d= -f2- | tr -d '"'"'" | tr -d '\r'
}

DB_NAME="$(get_env DB_NAME)"
DB_USERNAME="$(get_env DB_USERNAME)"

[ -n "$DB_NAME" ]     || die "DB_NAME not set in .env"
[ -n "$DB_USERNAME" ] || die "DB_USERNAME not set in .env"

mkdir -p "$BACKUP_ROOT"

# ---- Cleanup on exit: maintenance mode off, no half-written files left behind ----
MAINT_ENABLED=0
cleanup() {
    status=$?
    if [ "$MAINT_ENABLED" = "1" ]; then
        rm -f "$MAINT_FLAG"
        MAINT_ENABLED=0
        log "Maintenance mode disabled"
    fi
    if [ "$status" -ne 0 ]; then
        # An aborted run must not leave temporary files taking up disk space
        rm -f "${PG_OUT}.tmp" "${MINIO_OUT}.tmp"
    fi
}
trap cleanup EXIT

if [ "$USE_MAINTENANCE_MODE" = "1" ]; then
    mkdir -p "$(dirname "$MAINT_FLAG")"
    touch "$MAINT_FLAG"
    MAINT_ENABLED=1
    log "Maintenance mode enabled"
    sleep 3
fi

# ---- PostgreSQL ------------------------------------------------------------
log "Dumping database '${DB_NAME}' as '${DB_USERNAME}'..."

docker compose exec -T db pg_dump -U "$DB_USERNAME" "$DB_NAME" \
    | gzip > "${PG_OUT}.tmp" \
    || die "pg_dump failed"

# A gzipped empty dump is ~20 bytes; anything that small means failure.
if [ "$(stat -c%s "${PG_OUT}.tmp")" -lt 1000 ]; then
    die "Database dump is suspiciously small — aborting"
fi

mv "${PG_OUT}.tmp" "$PG_OUT"
log "Database backup written: $PG_OUT ($(du -h "$PG_OUT" | cut -f1))"

# ---- MinIO -----------------------------------------------------------------
EXIT_CODE=0
EXISTING_MINIO="$(find "$BACKUP_ROOT" -maxdepth 1 -name '*_minio_backup.tar.gz' | wc -l)"

if [ ! -d "${CODABENCH_DIR}/var/minio" ]; then
    log "WARNING: ${CODABENCH_DIR}/var/minio not found — skipping object store backup"
elif [ "$FORCE_MINIO_BACKUP" != "1" ] && [ "$(date +%u)" != "$MINIO_BACKUP_DAY" ] && [ "$EXISTING_MINIO" -gt 0 ]; then
    log "Object store archive is only taken on day ${MINIO_BACKUP_DAY} of the week (or with FORCE_MINIO_BACKUP=1) — skipping today"
else
    # The archive is at most as large as the folder it is made from
    NEEDED_KB="$(du -sk "${CODABENCH_DIR}/var/minio" | cut -f1)"
    FREE_KB="$(df -Pk "$BACKUP_ROOT" | awk 'NR==2 {print $4}')"
    if [ "$FREE_KB" -lt $(( NEEDED_KB + MIN_FREE_MB * 1024 )) ]; then
        log "WARNING: not enough free disk space for the object store archive: $(( FREE_KB / 1024 )) MB free, needs up to $(( NEEDED_KB / 1024 )) MB and ${MIN_FREE_MB} MB must stay free — skipped"
        EXIT_CODE=3
    else
        log "Archiving MinIO object store..."
        tar czf "${MINIO_OUT}.tmp" -C "${CODABENCH_DIR}/var" minio \
            || die "MinIO archive failed"
        mv "${MINIO_OUT}.tmp" "$MINIO_OUT"
        log "MinIO backup written: $MINIO_OUT ($(du -h "$MINIO_OUT" | cut -f1))"
    fi
fi

# ---- Maintenance mode off (also handled by trap) ---------------------------
if [ "$MAINT_ENABLED" = "1" ]; then
    rm -f "$MAINT_FLAG"
    MAINT_ENABLED=0
    log "Maintenance mode disabled"
fi

# ---- Retention -------------------------------------------------------------
log "Removing database backups older than ${RETENTION_DAYS_DB} days and keeping the newest ${MINIO_KEEP} object store archives..."
find "$BACKUP_ROOT" -maxdepth 1 -name '*_postgres_backup.sql.gz' -mtime "+${RETENTION_DAYS_DB}" -print -delete
find "$BACKUP_ROOT" -maxdepth 1 -name '*_minio_backup.tar.gz' | sort | head -n "-${MINIO_KEEP}" | while read -r old_archive; do
    rm -f "$old_archive"
    log "Removed old object store archive: $old_archive"
done
# Temporary files of runs that were interrupted
find "$BACKUP_ROOT" -maxdepth 1 -name '*.tmp' -mtime +0 -print -delete

log "Backup complete."
log "Current backups:"
ls -lh "$BACKUP_ROOT" | tail -n +2
log "Free space on the backup disk: $(df -Ph "$BACKUP_ROOT" | awk 'NR==2 {print $4 " free (" $5 " used)"}')"

exit "$EXIT_CODE"
