#!/usr/bin/env bash
# Conductor run script. Serves docs/ on the workspace's reserved port, the same
# way GitHub Pages serves the deployed site — so local URL paths match prod.
set -euo pipefail

: "${CONDUCTOR_PORT:?CONDUCTOR_PORT must be set by Conductor}"

exec python3 -m http.server --directory docs --bind 127.0.0.1 "$CONDUCTOR_PORT"
