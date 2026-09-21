#!/bin/bash
#
# Codabench backup — PostgreSQL dump + MinIO object store
#
# Creates, under BACKUP_ROOT:
#   YYYY_MM_DD_postgres_backup.sql.gz
#   YYYY_MM_DD_minio_backup.tar.gz
#
# Install:
#   sudo cp codabench-backup.sh /usr/local/bin/codabench-backup
#   sudo chmod +x /usr/local/bin/codabench-backup
#   sudo /usr/local/bin/codabench-backup          # test run
#
# Schedule (daily at 03:00):
#   sudo crontab -e
#   0 3 * * * /usr/local/bin/codabench-backup >> /var/log/codabench-backup.log 2>&1
#
set -euo pipefail

# ---- Configuration ---------------------------------------------------------
CODABENCH_DIR="/home/didimitrov/codabench"
BACKUP_ROOT="/var/backups/codabench"
RETENTION_DAYS=30

# Set to 1 to enable maintenance mode during the backup. This makes the
# database dump and the MinIO archive consistent with each other, at the cost
# of a short outage. Recommended once you have real users.
USE_MAINTENANCE_MODE=0

# ---- Derived ---------------------------------------------------------------
DATE_STAMP="$(date +%Y_%m_%d)"
PG_OUT="${BACKUP_ROOT}/${DATE_STAMP}_postgres_backup.sql.gz"
MINIO_OUT="${BACKUP_ROOT}/${DATE_STAMP}_minio_backup.tar.gz"
MAINT_FLAG="${CODABENCH_DIR}/maintenance_mode/maintenance.on"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { log "ERROR: $*" >&2; exit 1; }

# ---- Read DB credentials from .env ----------------------------------------
[ -d "$CODABENCH_DIR" ] || die "Codabench directory not found: $CODABENCH_DIR"
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

# ---- Maintenance mode on ---------------------------------------------------
MAINT_ENABLED=0
cleanup() {
    if [ "$MAINT_ENABLED" = "1" ]; then
        rm -f "$MAINT_FLAG"
        log "Maintenance mode disabled"
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
    rm -f "${PG_OUT}.tmp"
    die "Database dump is suspiciously small — aborting"
fi

mv "${PG_OUT}.tmp" "$PG_OUT"
log "Database backup written: $PG_OUT ($(du -h "$PG_OUT" | cut -f1))"

# ---- MinIO -----------------------------------------------------------------
if [ -d "${CODABENCH_DIR}/var/minio" ]; then
    log "Archiving MinIO object store..."
    tar czf "${MINIO_OUT}.tmp" -C "${CODABENCH_DIR}/var" minio \
        || die "MinIO archive failed"
    mv "${MINIO_OUT}.tmp" "$MINIO_OUT"
    log "MinIO backup written: $MINIO_OUT ($(du -h "$MINIO_OUT" | cut -f1))"
else
    log "WARNING: ${CODABENCH_DIR}/var/minio not found — skipping object store backup"
fi

# ---- Maintenance mode off (also handled by trap) ---------------------------
cleanup
MAINT_ENABLED=0

# ---- Retention -------------------------------------------------------------
log "Removing backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_ROOT" -maxdepth 1 -name '*_postgres_backup.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete
find "$BACKUP_ROOT" -maxdepth 1 -name '*_minio_backup.tar.gz'    -mtime "+${RETENTION_DAYS}" -print -delete

log "Backup complete."
log "Current backups:"
ls -lh "$BACKUP_ROOT" | tail -n +2