#!/usr/bin/env bash
# scripts/task4.sh  – example Task 4 script
set -euo pipefail
TASK_ID="${1:-unknown}"
echo "[task4] Running (task_id=$TASK_ID) at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
