"""Prepare compact ward data for the Changes page (docs/changes.html).

Mirrors scripts/06_prep_artifact_data.py — keeps only the fields the §3
flipped-wards appendix needs, in a compact array form ready to splice
into the page's <script> block.

Output: data/v1_changes_ward_data.json
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def main():
    with open(DATA / 'gm_all_wards_with_prior.json') as f:
        wards = json.load(f)

    out = []
    for w in wards:
        out.append({
            'borough': w['borough'],
            'ward': w['ward'],
            'winner': w.get('winner'),
            'prior_party': w.get('prior_party'),
            'prior_year': w.get('prior_year'),
            'flipped': w.get('flipped'),
            'match_type_prior': w.get('match_type_prior'),
            'density': w.get('density'),
            'pct_level4_plus': w.get('pct_level4_plus'),
            'pct_apprentice': w.get('pct_apprentice'),
            'pct_uk_born': w.get('pct_uk_born'),
        })

    with open(DATA / 'v1_changes_ward_data.json', 'w') as f:
        json.dump(out, f, indent=2)

    flipped = sum(1 for w in out if w.get('flipped'))
    held = sum(1 for w in out if w.get('flipped') is False)
    no_prior = sum(1 for w in out if w.get('prior_party') is None)
    pending = sum(1 for w in out if w.get('winner') in (None, 'Pending'))
    print(f'Saved v1_changes_ward_data.json — {len(out)} wards '
          f'(flipped={flipped}, held={held}, no_prior={no_prior}, pending={pending})')


if __name__ == '__main__':
    main()
