"""Merge hand-curated GM results (data/source/results_2026.csv) with scraped
non-GM 2026 results (data/results_2026_scraped.json) into one council-keyed
dict consumed by 02 and 04.

The CSV wins per (council, ward) where both sources cover the same seat —
hand-curated GM data carries share + turnout values that Wikipedia generally
doesn't publish, so we never overwrite a CSV row with a scrape. The scrape
supplies winners only (share + turnout left null) for every council the CSV
doesn't already cover.
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
    """Return council_name -> {ward: (winner, share, turnout)}.

    CSV rows go in first (in CSV order); scraped wards then fill in every
    (council, ward) the CSV didn't already supply.
    """
    results: dict[str, dict[str, tuple]] = {}
    with open(SOURCE / "results_2026.csv", newline="") as f:
        for row in csv.DictReader(f):
            results.setdefault(row["borough"], {})[row["ward"]] = (
                row["party"],
                _parse_float(row["share"]),
                _parse_float(row["turnout"]),
            )

    scraped_path = DATA / "results_2026_scraped.json"
    if scraped_path.exists():
        with open(scraped_path) as f:
            scraped = json.load(f)
        for council, wards in scraped.items():
            for ward, rec in wards.items():
                if council in results and ward in results[council]:
                    continue
                results.setdefault(council, {})[ward] = (rec["party"], None, None)

    return results


def main():
    RESULTS = load_results()

    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / "all_results.json", "w") as f:
        json.dump(RESULTS, f, indent=2)

    total = sum(len(v) for v in RESULTS.values())
    print(f"Saved {total} ward results across {len(RESULTS)} councils")
    for b, w in RESULTS.items():
        party_counts: dict[str, int] = {}
        for ward, (party, _, _) in w.items():
            party_counts[party] = party_counts.get(party, 0) + 1
        print(f"  {b:>30}: {len(w):>3} wards | {party_counts}")


if __name__ == "__main__":
    main()
