"""Compute Pearson correlations for all parties × all variables across:
- All declared GM wards (full sample)
- Each borough individually (subsample analysis)

Outputs: correlations.json
"""
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

with open(DATA / 'all_wards.json') as f:
    wards = json.load(f)

# Filter to declared (drop Pending)
declared = [w for w in wards if w.get('winner') not in ('Pending', None)]
print(f"Total declared wards: {len(declared)}")

# Variables to correlate
VARS = ['density', 'median_age', 'pct_under18', 'pct_18_29', 'pct_30_49', 'pct_50_64',
        'pct_65plus', 'pct_apprentice', 'pct_level4_plus', 'pct_no_qual', 'pct_soc123',
        'pct_owned', 'pct_social_rented', 'pct_private_rented', 'pct_uk_born', 'pct_wfh',
        'pct_female']

PARTIES = ['Green', 'Labour', 'Reform', 'LibDem', 'Conservative', 'Independent', 'Other']

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

# Compute correlations: each party vs each variable
results = {}
for party in PARTIES:
    party_indicator = [1 if w.get('winner') == party else 0 for w in declared]
    party_count = sum(party_indicator)
    if party_count < 3:
        continue  # skip parties with too few wards
    results[party] = {'n_wards': party_count}
    for var in VARS:
        var_vals = [w.get(var) for w in declared]
        r = pearson(var_vals, party_indicator)
        if r is not None:
            results[party][var] = round(r, 3)

# Print summary
print("\n=== Correlations: party-win indicator vs structural variable (all 213 declared wards) ===")
for party, data in results.items():
    n = data['n_wards']
    print(f"\n{party} (n={n}):")
    sorted_vars = sorted([(k, v) for k, v in data.items() if k != 'n_wards'],
                         key=lambda kv: -abs(kv[1]))
    for var, r in sorted_vars[:8]:
        print(f"  {var:>22}: {r:+.3f}")

# Also: party-by-party means for top variables
print("\n\n=== Mean structural profile by winning party ===")
TOP_VARS = ['density', 'median_age', 'pct_18_29', 'pct_65plus', 'pct_apprentice',
            'pct_level4_plus', 'pct_soc123', 'pct_owned', 'pct_social_rented',
            'pct_private_rented', 'pct_uk_born', 'pct_wfh', 'pct_female']
party_means = {}
for party in PARTIES:
    party_wards = [w for w in declared if w.get('winner') == party]
    if len(party_wards) < 3:
        continue
    party_means[party] = {'n': len(party_wards)}
    for var in TOP_VARS:
        vals = [w.get(var) for w in party_wards if w.get(var) is not None]
        if vals:
            party_means[party][var] = round(mean(vals), 2)

# Print
header = ['Var'] + [f"{p}({party_means[p]['n']})" for p in party_means]
print(f"{header[0]:<22} | " + " | ".join(f"{h:>14}" for h in header[1:]))
print("-" * (22 + 17 * len(header)))
for var in TOP_VARS:
    row = f"{var:<22} | "
    for p in party_means:
        v = party_means[p].get(var, '—')
        if isinstance(v, (int, float)):
            row += f"{v:>14.1f} | "
        else:
            row += f"{str(v):>14} | "
    print(row)

# Save
output = {
    'n_total': len(declared),
    'correlations': results,
    'means': party_means,
}
with open(DATA / 'correlations.json', 'w') as f:
    json.dump(output, f, indent=2)
print(f"\nSaved correlations.json")
