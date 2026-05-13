"""Shared pytest fixtures for tests/."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


@pytest.fixture(scope="session")
def pipeline_outputs():
    """Parsed JSONs the Current pipeline produces. Re-runs 04c (and 11 if
    needed) when the inputs are newer than current_winners.json so the tests
    see live data, not a stale snapshot. 04c is fast (~3s); 11 only fires
    if the raw extract is missing."""
    winners = DATA / "current_winners.json"
    raw = DATA / "current_winners_raw.json"
    overrides = ROOT / "data" / "source" / "current_ward_overrides.csv"
    councils = ROOT / "data" / "source" / "councils.yaml"

    def stale_against(target, *deps):
        if not target.exists():
            return True
        t = target.stat().st_mtime
        return any(d.exists() and d.stat().st_mtime > t for d in deps)

    if not raw.exists():
        subprocess.run([sys.executable, "scripts/11_extract_current.py"],
                       cwd=ROOT, check=True, capture_output=True)
    if stale_against(winners, raw, overrides, councils):
        subprocess.run([sys.executable, "scripts/04c_build_current_winners.py"],
                       cwd=ROOT, check=True, capture_output=True)

    return {
        "winners": json.loads(winners.read_text()),
        "ceds": json.loads((DATA / "ced_winners.json").read_text()),
    }
