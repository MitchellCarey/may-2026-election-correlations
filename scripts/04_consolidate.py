"""Consolidate Manchester (32) + Salford (20) + 161 new GM wards into one dataset.

Steps:
1. Load existing combined_wards.json (Manchester 29 + Salford 19)
2. Update Manchester pending wards with newly-declared results (Levenshulme/Rusholme = Green)
3. Add Salford Barton & Winton (missed in earlier extract)
4. Add pct_female to Manchester wards from earlier salford extract (Manchester data is in salford_2026.json or wards_v6.json)
5. Add the 161 new wards from all_gm_census.json + all_gm_results.json
6. Output: gm_all_wards.json (full 213-ward dataset)
"""
import pandas as pd
import json

# Load existing combined (48 wards, Manchester 29 + Salford 19)
with open('/home/claude/manchester/combined_wards.json') as f:
    existing = json.load(f)

# Load Manchester wards_v6 to extract pct_female
with open('/home/claude/manchester/wards_v6.json') as f:
    mv6 = json.load(f)
manc_v6 = mv6['wards']  # dict by ward name

# Update Manchester wards with pct_female
for entry in existing:
    if entry['borough'] == 'Manchester':
        wname = entry['ward']
        if wname in manc_v6 and 'pct_female' in manc_v6[wname]:
            entry['pct_female'] = manc_v6[wname]['pct_female']

# Update the Manchester pending wards (Levenshulme, Miles Platting, Rusholme)
# Levenshulme & Rusholme = Green (just declared per Northern Quota)
# Miles Platting & Newton Heath = still pending
for entry in existing:
    if entry['borough'] == 'Manchester':
        if entry['ward'] in ('Levenshulme', 'Rusholme'):
            entry['winner'] = 'Green'
        # Miles Platting & Newton Heath stays as Pending

# === Add Manchester pending wards if missing — they should already be in existing data with winner=None or Pending ===
manc_in_existing = {e['ward'] for e in existing if e['borough'] == 'Manchester'}
for ward, data in manc_v6.items():
    if ward not in manc_in_existing:
        # New entry
        entry = {
            'borough': 'Manchester',
            'ward': ward,
            'winner': data.get('winner', 'Pending'),
            'density': data.get('density'),
            'pct_18_29': data.get('pct_18_29'),
            'pct_65plus': data.get('pct_65plus'),
            'pct_under18': data.get('pct_under18'),
            'pct_30_49': data.get('pct_30_49'),
            'pct_50_64': data.get('pct_50_64'),
            'median_age': data.get('median_age'),
            'pct_soc123': data.get('pct_soc123'),
            'pct_apprentice': data.get('pct_apprentice'),
            'pct_level4_plus': data.get('pct_level4_plus'),
            'pct_no_qual': data.get('pct_no_qual'),
            'pct_owned': data.get('pct_owned'),
            'pct_social_rented': data.get('pct_social_rented'),
            'pct_private_rented': data.get('pct_private_rented'),
            'pct_uk_born': data.get('pct_uk_born'),
            'pct_wfh': data.get('pct_wfh'),
            'pct_female': data.get('pct_female'),
        }
        # Update Levenshulme/Rusholme winners
        if ward in ('Levenshulme', 'Rusholme'):
            entry['winner'] = 'Green'
        existing.append(entry)

# Print Manchester now
manc_now = [e for e in existing if e['borough'] == 'Manchester']
print(f"Manchester wards: {len(manc_now)}")
manc_winners = {}
for e in manc_now:
    w = e.get('winner', 'None')
    manc_winners[w] = manc_winners.get(w, 0) + 1
print(f"  Manchester winners: {manc_winners}")

# === Add Salford Barton & Winton ===
# We need to get Census data for it
df = pd.read_excel('/mnt/user-data/uploads/TS006-Population-Density-2021-wd-ONS.xlsx', sheet_name='Dataset')
bw_match = df[df['Electoral wards and divisions'].str.strip() == 'Barton and Winton']
print(f"\nBarton and Winton GSS: {bw_match.iloc[0]['Electoral wards and divisions Code'] if len(bw_match) else 'NOT FOUND'}")

# === Add the 161 new wards from new GM extraction ===
with open('/home/claude/manchester/all_gm_census.json') as f:
    new_census = json.load(f)
with open('/home/claude/manchester/all_gm_results.json') as f:
    new_results = json.load(f)

# Build list of new entries
existing_keys = {(e['borough'], e['ward']) for e in existing}
added = 0
for borough, wards in new_results.items():
    for ward, (winner, share, turnout) in wards.items():
        key = f"{borough}::{ward}"
        if key not in new_census:
            print(f"  WARNING: no census data for {key}")
            continue
        if (borough, ward) in existing_keys:
            continue  # already there (shouldn't be)
        c = new_census[key]
        entry = {
            'borough': borough,
            'ward': ward,
            'winner': winner,
            'winner_share': share,
            'turnout': turnout,
            'gss': c.get('gss'),
            'match_type': c.get('match_type'),
            'population': c.get('population'),
            'density': c.get('density'),
            'median_age': c.get('median_age'),
            'pct_under18': c.get('pct_under18'),
            'pct_18_29': c.get('pct_18_29'),
            'pct_30_49': c.get('pct_30_49'),
            'pct_50_64': c.get('pct_50_64'),
            'pct_65plus': c.get('pct_65plus'),
            'pct_soc123': c.get('pct_soc123'),
            'pct_apprentice': c.get('pct_apprentice'),
            'pct_level4_plus': c.get('pct_level4_plus'),
            'pct_no_qual': c.get('pct_no_qual'),
            'pct_owned': c.get('pct_owned'),
            'pct_social_rented': c.get('pct_social_rented'),
            'pct_private_rented': c.get('pct_private_rented'),
            'pct_uk_born': c.get('pct_uk_born'),
            'pct_wfh': c.get('pct_wfh'),
            'pct_female': c.get('pct_female'),
        }
        existing.append(entry)
        added += 1

print(f"\nAdded {added} new wards")
print(f"Total wards: {len(existing)}")

# Per-borough counts
bcounts = {}
for e in existing:
    b = e['borough']
    bcounts[b] = bcounts.get(b, 0) + 1
print(f"\nPer-borough:")
for b, n in sorted(bcounts.items()):
    print(f"  {b}: {n}")

# Save
with open('/home/claude/manchester/gm_all_wards.json', 'w') as f:
    json.dump(existing, f, indent=2)
print(f"\nSaved gm_all_wards.json")
