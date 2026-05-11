"""Load hand-curated 2026 ward results from data/source/results_2026.csv
and consolidate into the legacy nested dict shape that downstream scripts
(02, 04) consume.

The CSV is the editable source of truth: one row per ward with
(lad_code, borough, ward, party, share, turnout). Empty share/turnout
cells become null in the JSON output. CSV row order is preserved end
to end so the emitted JSON is stable across runs.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"


def _parse_float(s: str):
    return float(s) if s != "" else None


def load_results():
    """Return borough -> {ward: (winner, share, turnout)} preserving CSV order."""
    results: dict[str, dict[str, tuple]] = {}
    with open(SOURCE / "results_2026.csv", newline="") as f:
        for row in csv.DictReader(f):
            borough = row["borough"]
            ward = row["ward"]
            party = row["party"]
            share = _parse_float(row["share"])
            turnout = _parse_float(row["turnout"])
            results.setdefault(borough, {})[ward] = (party, share, turnout)
    return results


def main():
    RESULTS = load_results()

    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / "all_gm_results.json", "w") as f:
        json.dump(RESULTS, f, indent=2)

    total = sum(len(v) for v in RESULTS.values())
    print(f"Saved {total} ward results across {len(RESULTS)} boroughs")
    for b, w in RESULTS.items():
        party_counts: dict[str, int] = {}
        for ward, (party, _, _) in w.items():
            party_counts[party] = party_counts.get(party, 0) + 1
        print(f"  {b:>12}: {len(w):>2} wards | {party_counts}")


if __name__ == "__main__":
    main()
