#!/usr/bin/env bash
# Mac/Linux: runs the screener with Moomoo OpenD data. Schedule with cron (see README).
# OpenD must already be running and logged in.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
mkdir -p logs
DATA_SOURCE=moomoo python screener.py >> logs/screener.log 2>&1
