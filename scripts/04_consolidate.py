"""Consolidate every (borough, ward) into the master ward record.

Reads:
  - data/all_results.json    (winner / share / turnout per ward, from 01)
  - data/all_census.json     (Census 2021 variables per (borough, ward), from 03)

Writes data/all_wards.json — a flat list of dicts, one per ward, where each
record carries the winner + every Census variable we extract. Wards with no
Census match drop out with a warning. Order is whatever all_results.json
provides (which is whatever results_2026.csv provides, sorted lad_code +
ward).

Manchester and Salford used to come in via a pre-Census legacy snapshot
(combined_wards.json + wards_v6.json) plus hand-applied patches inside this
script. That data now lives in results_2026.csv alongside every other GM
borough, and Census comes from all_census.json like everything else.
"""
import json
from pathlib import Path

from _councils import load as load_councils

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

COUNCIL_LAD = {c["name"]: c["lad_code"] for c in load_councils()}


CENSUS_FIELDS = [
    'population', 'density', 'median_age',
    'pct_under18', 'pct_18_29', 'pct_30_49', 'pct_50_64', 'pct_65plus',
    'pct_soc123', 'pct_apprentice', 'pct_level4_plus', 'pct_no_qual',
    'pct_owned', 'pct_social_rented', 'pct_private_rented',
    'pct_uk_born', 'pct_wfh', 'pct_female',
    'pct_white', 'pct_asian', 'pct_black', 'pct_mixed', 'pct_other_ethnic',
]


def main():
    with open(DATA / 'all_census.json') as f:
        census = json.load(f)
    with open(DATA / 'all_results.json') as f:
        results = json.load(f)

    out = []
    missing = []
    for borough, wards in results.items():
        for ward, (winner, share, turnout) in wards.items():
            key = f"{borough}::{ward}"
            c = census.get(key)
            if c is None:
                missing.append(key)
                continue
            entry = {
                'borough': borough,
                'lad_code': COUNCIL_LAD.get(borough),
                'ward': ward,
                'winner': winner,
                'winner_share': share,
                'turnout': turnout,
                'gss': c.get('gss'),
                'match_type': c.get('match_type'),
            }
            for f_ in CENSUS_FIELDS:
                entry[f_] = c.get(f_)
            out.append(entry)

    if missing:
        print(f'WARNING: {len(missing)} wards have no Census match:')
        for k in missing:
            print(f'  {k}')

    with open(DATA / 'all_wards.json', 'w') as f:
        json.dump(out, f, indent=2)

    bcounts: dict[str, int] = {}
    for e in out:
        bcounts[e['borough']] = bcounts.get(e['borough'], 0) + 1
    print(f'\nSaved all_wards.json — {len(out)} wards')
    for b, n in sorted(bcounts.items()):
        print(f'  {b}: {n}')


if __name__ == '__main__':
    main()
