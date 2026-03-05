#!/usr/bin/env bash
# =============================================================================
# deploy/auto_update.sh
#
# Pulls the latest changes from origin and, if anything changed, restarts the
# tasker-talker-subscriber systemd service (if it exists).
#
# Designed to be run by cron or any scheduler.  Example crontab entry to poll
# every 5 minutes:
#
#   */5 * * * * /path/to/tasker-talker/deploy/auto_update.sh >> /var/log/tasker-talker-update.log 2>&1
#
# Usage:
#   ./deploy/auto_update.sh [--repo-dir <path>] [--service <name>] [--no-restart]
# =============================================================================

set -euo pipefail

# ---------- defaults ---------------------------------------------------------
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="tasker-talker-subscriber"
DO_RESTART=true

# ---------- argument parsing -------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-dir)   REPO_DIR="$2";    shift 2 ;;
    --service)    SERVICE_NAME="$2"; shift 2 ;;
    --no-restart) DO_RESTART=false; shift   ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ---------- helpers ----------------------------------------------------------
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# ---------- pull -------------------------------------------------------------
cd "$REPO_DIR"

log "Fetching from origin..."
git fetch origin

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse '@{u}')

if [[ "$LOCAL" == "$REMOTE" ]]; then
  log "Already up to date ($LOCAL). Nothing to do."
  exit 0
fi

log "New commits available.  Pulling..."
git pull --ff-only origin

NEW=$(git rev-parse HEAD)
log "Updated: $LOCAL → $NEW"

# ---------- restart service --------------------------------------------------
if [[ "$DO_RESTART" == true ]]; then
  if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    log "Restarting service: $SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"
    log "Service restarted."
  else
    log "Service '$SERVICE_NAME' is not running or not found — skipping restart."
  fi
fi
