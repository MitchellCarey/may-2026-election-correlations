"""Compute Pearson correlations for party-win indicator vs Census variables,
per region (gm + gb).

Output: data/correlations.json
  {
    "n_total":      <gm-only count, for backward compat with 08>,
    "correlations": <gm block, legacy key>,
    "means":        <gm block, legacy key>,
    "regions": {
      "gm": {"n_total", "correlations", "means"},
      "gb": {"n_total", "correlations", "means"},
    }
  }

The legacy top-level keys mirror regions.gm so older consumers (currently
08_parallel_chart.py) keep working. 07 reads regions[region] when given
a --region flag.
"""
import json
from pathlib import Path
from statistics import mean

from _councils import lad_codes_for

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

VARS = ['density', 'median_age', 'pct_under18', 'pct_18_29', 'pct_30_49', 'pct_50_64',
        'pct_65plus', 'pct_apprentice', 'pct_level4_plus', 'pct_no_qual', 'pct_soc123',
        'pct_owned', 'pct_social_rented', 'pct_private_rented', 'pct_uk_born', 'pct_wfh',
        'pct_female',
        'pct_white', 'pct_asian', 'pct_black', 'pct_mixed', 'pct_other_ethnic']
PARTIES = ['Green', 'Labour', 'Reform', 'LibDem', 'Conservative', 'Independent', 'Other']
TOP_VARS = ['density', 'median_age', 'pct_18_29', 'pct_65plus', 'pct_apprentice',
            'pct_level4_plus', 'pct_soc123', 'pct_owned', 'pct_social_rented',
            'pct_private_rented', 'pct_uk_born', 'pct_wfh', 'pct_female',
            'pct_white', 'pct_asian', 'pct_black', 'pct_mixed', 'pct_other_ethnic']


def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    xs2, ys2 = zip(*pairs)
    mx, my = mean(xs2), mean(ys2)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    sx = sum((x - mx) ** 2 for x, _ in pairs) ** 0.5
    sy = sum((y - my) ** 2 for _, y in pairs) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return num / (sx * sy)


def compute_block(wards):
    declared = [w for w in wards if w.get('winner') not in ('Pending', None)]
    results = {}
    for party in PARTIES:
        ind = [1 if w.get('winner') == party else 0 for w in declared]
        if sum(ind) < 3:
            continue
        results[party] = {'n_wards': sum(ind)}
        for var in VARS:
            r = pearson([w.get(var) for w in declared], ind)
            if r is not None:
                results[party][var] = round(r, 3)
    means_ = {}
    for party in PARTIES:
        party_wards = [w for w in declared if w.get('winner') == party]
        if len(party_wards) < 3:
            continue
        means_[party] = {'n': len(party_wards)}
        for var in TOP_VARS:
            vals = [w.get(var) for w in party_wards if w.get(var) is not None]
            if vals:
                means_[party][var] = round(mean(vals), 2)
    return {'n_total': len(declared), 'correlations': results, 'means': means_}


def main():
    with open(DATA / 'all_wards.json') as f:
        wards = json.load(f)

    gm_codes = lad_codes_for('gm')
    gm_wards = [w for w in wards if w.get('lad_code') in gm_codes]
    gm_block = compute_block(gm_wards)
    gb_block = compute_block(wards)

    output = {
        # Legacy top-level keys mirror regions.gm — kept for 08's sake.
        **gm_block,
        'regions': {'gm': gm_block, 'gb': gb_block},
    }
    with open(DATA / 'correlations.json', 'w') as f:
        json.dump(output, f, indent=2)
    print(f'Saved correlations.json '
          f'(gm: {gm_block["n_total"]} declared wards, '
          f'gb: {gb_block["n_total"]} declared wards)')


if __name__ == '__main__':
    main()
