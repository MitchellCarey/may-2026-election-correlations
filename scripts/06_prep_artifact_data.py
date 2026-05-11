"""Build v12: Greater Manchester ward analysis (213 wards, 10 boroughs).
Inherits CSS structure from v11 (mobile-first), but replaces all data with
the consolidated full-GM dataset.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

with open(DATA / 'all_wards.json') as f:
    wards = json.load(f)
with open(DATA / 'correlations.json') as f:
    corr = json.load(f)

declared = [w for w in wards if w.get('winner') not in ('Pending', None)]

# Borough breakdown for §2
borough_breakdown = {}
for w in wards:
    b = w['borough']
    if b not in borough_breakdown:
        borough_breakdown[b] = {'wards': []}
    borough_breakdown[b]['wards'].append(w)

# Borough party tallies
for b, data in borough_breakdown.items():
    counts = {}
    for w in data['wards']:
        winner = w.get('winner', 'Pending')
        counts[winner] = counts.get(winner, 0) + 1
    data['counts'] = counts

# Print it
for b in sorted(borough_breakdown):
    d = borough_breakdown[b]
    print(f"{b:>12}: {len(d['wards'])} wards | {d['counts']}")

# === Build the JS data structure for the artifact ===
# All wards as a single array, ordered by borough then ward
ward_data_js = []
for b in sorted(borough_breakdown):
    for w in sorted(borough_breakdown[b]['wards'], key=lambda x: x['ward']):
        ward_data_js.append({
            'borough': b,
            'lad_code': w.get('lad_code'),
            'ward': w['ward'],
            'winner': w.get('winner', 'Pending'),
            'density': w.get('density'),
            'median_age': w.get('median_age'),
            'pct_18_29': w.get('pct_18_29'),
            'pct_65plus': w.get('pct_65plus'),
            'pct_apprentice': w.get('pct_apprentice'),
            'pct_level4_plus': w.get('pct_level4_plus'),
            'pct_soc123': w.get('pct_soc123'),
            'pct_owned': w.get('pct_owned'),
            'pct_social_rented': w.get('pct_social_rented'),
            'pct_private_rented': w.get('pct_private_rented'),
            'pct_uk_born': w.get('pct_uk_born'),
            'pct_wfh': w.get('pct_wfh'),
            'pct_female': w.get('pct_female'),
            'turnout': w.get('turnout'),
            'match_type': w.get('match_type'),
        })

with open(DATA / 'v12_ward_data.json', 'w') as f:
    json.dump(ward_data_js, f, indent=2)
print(f"\nSaved {len(ward_data_js)} wards to v12_ward_data.json")
