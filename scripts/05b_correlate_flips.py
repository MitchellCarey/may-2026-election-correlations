"""Compute Pearson correlations of Census variables vs. "flipped to party X",
per region (gm + gb).

    won_by_X      = (winner == X)                                          # 05_correlate
    flipped_to_X  = (winner == X AND prior_party != X AND prior is known)  # this script

Output JSON shape matches 05's correlations.json — legacy top-level keys
(GM block) for 07b's current consumer, plus a `regions` block keyed by
region. Parties with fewer than MIN_FLIPS flipped wards are skipped —
Pearson r on n<5 is essentially noise.
"""
import json
from pathlib import Path
from statistics import mean

from _councils import lad_codes_for

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

MIN_FLIPS = 5

VARS = ['density', 'median_age', 'pct_under18', 'pct_18_29', 'pct_30_49', 'pct_50_64',
        'pct_65plus', 'pct_apprentice', 'pct_level4_plus', 'pct_no_qual', 'pct_soc123',
        'pct_owned', 'pct_social_rented', 'pct_private_rented', 'pct_uk_born', 'pct_wfh',
        'pct_female']
PARTIES = ['Green', 'Labour', 'Reform', 'LibDem', 'Conservative', 'Independent', 'Other']
TOP_VARS = ['density', 'median_age', 'pct_18_29', 'pct_65plus', 'pct_apprentice',
            'pct_level4_plus', 'pct_soc123', 'pct_owned', 'pct_social_rented',
            'pct_private_rented', 'pct_uk_born', 'pct_wfh', 'pct_female']


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
    sample = [w for w in wards
              if w.get('winner') not in ('Pending', None)
              and w.get('prior_party') is not None]
    correlations = {}
    for party in PARTIES:
        ind = [1 if (w['winner'] == party and w['prior_party'] != party) else 0 for w in sample]
        n_flipped = sum(ind)
        if n_flipped < MIN_FLIPS:
            continue
        rec = {'n_flipped': n_flipped}
        for var in VARS:
            r = pearson([w.get(var) for w in sample], ind)
            if r is not None:
                rec[var] = round(r, 3)
        correlations[party] = rec
    means_ = {}
    for party in PARTIES:
        flipped = [w for w in sample if w['winner'] == party and w['prior_party'] != party]
        if len(flipped) < MIN_FLIPS:
            continue
        rec = {'n': len(flipped)}
        for var in TOP_VARS:
            vals = [w.get(var) for w in flipped if w.get(var) is not None]
            if vals:
                rec[var] = round(mean(vals), 2)
        means_[party] = rec
    return {'n_total': len(sample), 'min_flips': MIN_FLIPS,
            'correlations': correlations, 'means': means_}


def main():
    with open(DATA / 'all_wards_with_prior.json') as f:
        wards = json.load(f)

    gm_codes = lad_codes_for('gm')
    gm_block = compute_block([w for w in wards if w.get('lad_code') in gm_codes])
    gb_block = compute_block(wards)

    output = {
        **gm_block,
        'regions': {'gm': gm_block, 'gb': gb_block},
    }
    with open(DATA / 'flip_correlations.json', 'w') as f:
        json.dump(output, f, indent=2)
    print(f'Saved flip_correlations.json '
          f'(gm: {len(gm_block["correlations"])} parties, '
          f'gb: {len(gb_block["correlations"])} parties above MIN_FLIPS={MIN_FLIPS})')


if __name__ == '__main__':
    main()
