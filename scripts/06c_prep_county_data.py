"""Build the per-district artifact for the GB-map's "Counties" toggle.

Reads:
  - data/county_results_2026.json   (from 01c — top-of-poll party per district
                                     within each English county council)
  - data/county_results_prior.json  (same shape, 2021)
  - data/ward_geoms.json            (counties block from 09 — CTY24CD → name +
                                     list of constituent LAD24CDs; boroughs
                                     block — LAD24CD → name)

Writes data/v1_county_data.json — keyed by district LAD24CD so 07c can paint
each constituent district polygon directly:

  { LAD24CD: {
      "county_lad":      "E10000012",
      "county":          "Essex",
      "district":        "Basildon",
      "winner_2026":     "Reform",
      "winner_prior":    "Conservative",
      "flipped":         true,
      "seats_won_2026":  6,
      "total_seats_2026": 9
    } }

District-name matching is wiki H3 → LAD24NM with light normalisation. Misses
are fatal because a silent drop would mean an English district renders grey
in a county that voted on it.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def normalise(s: str) -> str:
    """Loose name match, mirroring 07c's normaliser. Strips punctuation/case
    drift between Wikipedia H3 names and the LAD24NM in ward_geoms.json."""
    s = s.lower().replace('&', 'and').replace('.', '')
    s = s.replace("’", "").replace("'", "")
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def main():
    with open(DATA / 'county_results_2026.json') as f:
        cty_2026 = json.load(f)
    with open(DATA / 'county_results_prior.json') as f:
        cty_prior = json.load(f)
    with open(DATA / 'ward_geoms.json') as f:
        geoms = json.load(f)

    counties = geoms.get('counties', {})
    boroughs = geoms.get('boroughs', {})

    # Reverse lookup: county name → CTY24CD (for connecting Wikipedia council
    # name to the geom-side county code).
    name_to_cty = {c['name']: code for code, c in counties.items()}

    out: dict[str, dict] = {}
    misses: list[tuple[str, str]] = []

    for county_name, districts_2026 in cty_2026.items():
        cty_code = name_to_cty.get(county_name)
        if cty_code is None:
            misses.append((county_name, '(no county geom)'))
            continue
        # LAD24CD → LAD24NM for districts inside this county.
        lads_in_county = counties[cty_code]['lads']
        lad_by_norm = {
            normalise(boroughs[lad]['name']): lad
            for lad in lads_in_county if lad in boroughs
        }

        prior_districts = cty_prior.get(county_name, {})
        for district_name, rec_2026 in districts_2026.items():
            lad = lad_by_norm.get(normalise(district_name))
            if lad is None:
                misses.append((county_name, district_name))
                continue
            rec_prior = prior_districts.get(district_name) or \
                next((v for k, v in prior_districts.items()
                      if normalise(k) == normalise(district_name)), None)
            winner_2026 = rec_2026['party']
            winner_prior = rec_prior['party'] if rec_prior else None
            out[lad] = {
                'county_lad':       cty_code,
                'county':           county_name,
                'district':         district_name,
                'winner_2026':      winner_2026,
                'winner_prior':     winner_prior,
                'flipped':          (winner_prior is not None
                                     and winner_prior != winner_2026),
                'seats_won_2026':   rec_2026['seats_won'],
                'total_seats_2026': rec_2026['total_seats'],
            }

    with open(DATA / 'v1_county_data.json', 'w') as f:
        json.dump(out, f, indent=2)

    n_districts = sum(len(v) for v in cty_2026.values())
    print(f'Saved v1_county_data.json — {len(out)} of {n_districts} districts joined '
          f'across {len(cty_2026)} counties')
    if misses:
        print(f'  ! {len(misses)} miss(es):', file=sys.stderr)
        for cty, dist in misses:
            print(f'    - {cty} :: {dist}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
