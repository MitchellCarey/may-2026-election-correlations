"""Compute Pearson correlations of Census variables vs. "flipped to party X".

Mirror of 05_correlate.py, but the dependent variable is changed:

    won_by_X      = (winner == X)                                 # 05_correlate
    flipped_to_X  = (winner == X AND prior_party != X AND prior_party is not None)  # this script

Output JSON shape matches correlations.json exactly so 07b can reuse the
matrix-renderer JS verbatim. Parties with fewer than MIN_FLIPS flipped wards
are skipped — Pearson r on n<5 is essentially noise.
"""
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

MIN_FLIPS = 5  # parties with fewer flipped wards are excluded from the analysis

VARS = ['density', 'median_age', 'pct_under18', 'pct_18_29', 'pct_30_49', 'pct_50_64',
        'pct_65plus', 'pct_apprentice', 'pct_level4_plus', 'pct_no_qual', 'pct_soc123',
        'pct_owned', 'pct_social_rented', 'pct_private_rented', 'pct_uk_born', 'pct_wfh',
        'pct_female']

PARTIES = ['Green', 'Labour', 'Reform', 'LibDem', 'Conservative', 'Independent', 'Other']

# Same TOP_VARS list as 05_correlate.py for consistency across pages
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


def main():
    with open(DATA / 'all_wards_with_prior.json') as f:
        wards = json.load(f)

    # Analysis sample: declared 2026 winner AND known prior party (so flipped is defined)
    sample = [w for w in wards
              if w.get('winner') not in ('Pending', None)
              and w.get('prior_party') is not None]
    print(f'Analysis sample: {len(sample)} wards (of {len(wards)} total) — '
          f'have both 2026 winner and known prior_party')

    # Per-party correlations
    correlations = {}
    for party in PARTIES:
        flip_indicator = [
            1 if (w['winner'] == party and w['prior_party'] != party) else 0
            for w in sample
        ]
        n_flipped = sum(flip_indicator)
        if n_flipped < MIN_FLIPS:
            print(f'  Skipping {party}: only {n_flipped} flipped wards (< {MIN_FLIPS})')
            continue
        rec = {'n_flipped': n_flipped}
        for var in VARS:
            var_vals = [w.get(var) for w in sample]
            r = pearson(var_vals, flip_indicator)
            if r is not None:
                rec[var] = round(r, 3)
        correlations[party] = rec

    # Per-party mean Census profile of wards that flipped TO that party
    means = {}
    for party in PARTIES:
        flipped_wards = [w for w in sample
                         if w['winner'] == party and w['prior_party'] != party]
        if len(flipped_wards) < MIN_FLIPS:
            continue
        rec = {'n': len(flipped_wards)}
        for var in TOP_VARS:
            vals = [w.get(var) for w in flipped_wards if w.get(var) is not None]
            if vals:
                rec[var] = round(mean(vals), 2)
        means[party] = rec

    # Print summary
    print('\n=== Top |r| Census correlations per "flipped to" indicator ===')
    for party, rec in correlations.items():
        items = sorted(((k, v) for k, v in rec.items() if k != 'n_flipped'),
                       key=lambda kv: -abs(kv[1]))
        print(f'\n{party} (n_flipped={rec["n_flipped"]}):')
        for var, r in items[:8]:
            print(f'  {var:>22}: {r:+.3f}')

    output = {
        'n_total': len(sample),
        'min_flips': MIN_FLIPS,
        'correlations': correlations,
        'means': means,
    }
    with open(DATA / 'flip_correlations.json', 'w') as f:
        json.dump(output, f, indent=2)
    print(f'\nSaved flip_correlations.json '
          f'({len(correlations)} parties above MIN_FLIPS={MIN_FLIPS})')


if __name__ == '__main__':
    main()
