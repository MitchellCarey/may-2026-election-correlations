#!/usr/bin/env bash
# Conductor archive script. No daemons or DBs to tear down — just reclaim disk
# from the venv and Python bytecode caches. Leaves data/ alone (the committed
# JSON outputs and the large cached source downloads are expensive to refetch).
set -euo pipefail

rm -rf .venv
find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
