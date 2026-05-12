#!/usr/bin/env bash
# Conductor workspace setup. Provisions a Python venv for the data pipeline.
# The site itself (docs/*.html) is committed and needs no build step; the venv
# is only required if you re-run scripts/0*.py to regenerate the spliced data.
set -euo pipefail

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo
echo "Setup complete."
echo "Note: data/source/*.xlsx and the GB GeoJSON are not auto-fetched."
echo "      See data/source/README.md if you intend to re-run the pipeline."
