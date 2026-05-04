#!/bin/bash
# Cron entry point for the retail sales pipeline.
# Cron runs with a bare environment — no PATH, no conda — so everything
# must use absolute paths.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="/opt/anaconda3/bin/python"
LOG_FILE="$PROJECT_DIR/logs/cron.log"

cd "$PROJECT_DIR"

echo "-------- $(date '+%Y-%m-%d %H:%M:%S') starting --------" >> "$LOG_FILE"
$PYTHON -m src.main >> "$LOG_FILE" 2>&1
echo "-------- $(date '+%Y-%m-%d %H:%M:%S') done --------" >> "$LOG_FILE"
