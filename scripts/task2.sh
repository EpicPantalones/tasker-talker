#!/usr/bin/env bash
# scripts/task2.sh  – example Task 2 script
set -euo pipefail
echo "[task2] Running at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[task2] MY_ENV_VAR=${MY_ENV_VAR:-<not set>}"
