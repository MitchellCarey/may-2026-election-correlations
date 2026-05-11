"""Compute each party's structural profile before (2022/2021) vs after (2026).

For every party, compares:
  - mean Census profile of wards held in the prior election
  - mean Census profile of wards held after the May 2026 vote
  - delta (2026 − 2022) for each variable

…and (less prominently) the party-win-vs-Census Pearson r in each period.

Tells the story of *coalition shift*: Labour's 2026 wards are drawn from a
different slice of GM than its 2022 wards, even though both sets are called
"Labour". Reform's 2022 column is empty because it didn't win any GM ward
in 2022 — its 104 wins are entirely a new coalition.

Output: data/before_after.json
"""
import json
from pathlib import Path
from statistics import mean

from _councils import lad_codes_for

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

GM_LAD_CODES = lad_codes_for('gm')

PARTIES = ['Reform', 'Green', 'Labour', 'LibDem', 'Conservative', 'Independent', 'Other']

# Same variable list as 05_correlate.py / 05b_correlate_flips.py
VARS = ['density', 'median_age', 'pct_under18', 'pct_18_29', 'pct_30_49', 'pct_50_64',
        'pct_65plus', 'pct_apprentice', 'pct_level4_plus', 'pct_no_qual', 'pct_soc123',
        'pct_owned', 'pct_social_rented', 'pct_private_rented', 'pct_uk_born', 'pct_wfh',
        'pct_female']

# Subset surfaced on the page (parallel to TOP_VARS in 05_correlate.py)
TOP_VARS = ['density', 'median_age', 'pct_18_29', 'pct_65plus', 'pct_apprentice',
            'pct_level4_plus', 'pct_soc123', 'pct_owned', 'pct_social_rented',
            'pct_private_rented', 'pct_uk_born', 'pct_wfh', 'pct_female']

MIN_N = 3  # below this, means/r are too noisy to bother reporting


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


def compute_means(wards):
    out = {}
    for var in VARS:
        vals = [w.get(var) for w in wards if w.get(var) is not None]
        if vals:
            out[var] = round(mean(vals), 2)
    return out


def compute_correlations(sample, indicator):
    out = {}
    for var in VARS:
        var_vals = [w.get(var) for w in sample]
        r = pearson(var_vals, indicator)
        if r is not None:
            out[var] = round(r, 3)
    return out


def main():
    with open(DATA / 'all_wards_with_prior.json') as f:
        wards = json.load(f)

    # Phase B transitional filter — restrict to GM until 07b accepts --region.
    wards = [w for w in wards if w.get('lad_code') in GM_LAD_CODES]

    # 2022/2021 sample: wards with a known prior_party (boundary-changed wards
    # without a clean predecessor are excluded by definition).
    sample_2022 = [w for w in wards if w.get('prior_party') is not None]
    # 2026 sample: declared wards (Pending excluded).
    sample_2026 = [w for w in wards if w.get('winner') not in ('Pending', None)]

    # Pre-build indicator vectors for correlations
    out = {
        'n_total_2022': len(sample_2022),
        'n_total_2026': len(sample_2026),
        'top_vars': TOP_VARS,
        'min_n': MIN_N,
        'parties': {},
    }

    for party in PARTIES:
        wards_2022 = [w for w in sample_2022 if w['prior_party'] == party]
        wards_2026 = [w for w in sample_2026 if w['winner'] == party]
        n22, n26 = len(wards_2022), len(wards_2026)
        rec = {'n_2022': n22, 'n_2026': n26}

        if n22 >= MIN_N:
            rec['means_2022'] = compute_means(wards_2022)
            indicator = [1 if w['prior_party'] == party else 0 for w in sample_2022]
            rec['r_2022'] = compute_correlations(sample_2022, indicator)
        if n26 >= MIN_N:
            rec['means_2026'] = compute_means(wards_2026)
            indicator = [1 if w['winner'] == party else 0 for w in sample_2026]
            rec['r_2026'] = compute_correlations(sample_2026, indicator)

        if n22 >= MIN_N and n26 >= MIN_N:
            rec['delta_means'] = {
                v: round(rec['means_2026'][v] - rec['means_2022'][v], 2)
                for v in rec['means_2022']
                if v in rec['means_2026']
            }
            rec['delta_r'] = {
                v: round(rec['r_2026'].get(v, 0) - rec['r_2022'].get(v, 0), 3)
                for v in rec['r_2022']
                if v in rec['r_2026']
            }

        out['parties'][party] = rec

    with open(DATA / 'before_after.json', 'w') as f:
        json.dump(out, f, indent=2)

    print(f'Saved before_after.json')
    print(f'  n_total: 2022={out["n_total_2022"]} | 2026={out["n_total_2026"]}\n')
    print(f'  Per-party seat counts (2022 → 2026):')
    for p, r in out['parties'].items():
        delta = r['n_2026'] - r['n_2022']
        sign = '+' if delta >= 0 else ''
        print(f'    {p:>14}:  {r["n_2022"]:>3}  →  {r["n_2026"]:>3}   ({sign}{delta})')

    # Highlight a couple of striking shifts so the build log is informative
    print('\n  Sample mean shifts (2026 − 2022):')
    for p in ['Labour', 'Green', 'LibDem']:
        r = out['parties'].get(p, {})
        if 'delta_means' not in r:
            continue
        deltas = sorted(r['delta_means'].items(), key=lambda kv: -abs(kv[1]))[:3]
        deltas_str = ', '.join(f'{v} {("+" if d>=0 else "")}{d}' for v, d in deltas)
        print(f'    {p:>14}: {deltas_str}')


if __name__ == '__main__':
    main()
