"""For each ward in 2026 results, find its Census 2021 GSS code.

Approach:
- Try exact match within the borough's GSS code range
- Try with & vs and
- Try with parenthesised borough suffix (e.g. "Norden (Rochdale)")
- For boundary-shifted or punctuation-divergent wards: use the
  (lad_code, scraped_name) -> gss_name overrides in
  data/source/ward_name_overrides.csv
- Wards with no clean Census equivalent are dropped (logged)
"""
import csv
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"


def load_overrides():
    """Return {(lad_code, scraped_name): gss_name} from the overrides CSV."""
    overrides: dict[tuple[str, str], str] = {}
    with open(SOURCE / "ward_name_overrides.csv", newline="") as f:
        for row in csv.DictReader(f):
            overrides[(row["lad_code"], row["scraped_name"])] = row["gss_name"]
    return overrides


OVERRIDES = load_overrides()

# Borough's GSS LA codes (E08000xxx) for disambiguating wards that share names across boroughs
BOROUGH_LA = {
    'Bolton':     'E08000001',
    'Bury':       'E08000002',
    'Manchester': 'E08000003',
    'Oldham':     'E08000004',
    'Rochdale':   'E08000005',
    'Salford':    'E08000006',
    'Stockport':  'E08000007',
    'Tameside':   'E08000008',
    'Trafford':   'E08000009',
    'Wigan':      'E08000010',
}

# Ward GSS code prefix ranges per borough (heuristic; verified by spot-check)
BOROUGH_CODE_RANGES = {
    'Bolton':     [('E05000650', 'E05000680')],  # Old wards — used for fuzzy
    'Bury':       [('E05014152', 'E05014170')],  # New 2022 wards
    'Manchester': [('E05011350', 'E05011385')],
    'Oldham':     [('E05000719', 'E05000740')],
    'Rochdale':   [('E05014033', 'E05014053')],
    'Salford':    [('E05013018', 'E05013040')],  # E05013018 = Barton & Winton
    'Stockport':  [('E05000779', 'E05000810')],
    'Tameside':   [('E05000800', 'E05000820')],
    'Trafford':   [('E05000819', 'E05000840')],
    'Wigan':      [('E05000840', 'E05000870')],
}

def find_gss_code(borough, ward_name, df):
    """Find GSS code for ward with progressive fallback strategies."""
    # 1. Try exact match within borough's code range
    ranges = BOROUGH_CODE_RANGES[borough]
    df_borough = df[df['Electoral wards and divisions Code'].apply(
        lambda c: any(lo <= c <= hi for lo, hi in ranges))]
    
    # Try exact name (within borough)
    match = df_borough[df_borough['Electoral wards and divisions'].str.strip() == ward_name]
    if len(match) >= 1:
        return match.iloc[0]['Electoral wards and divisions Code'], 'exact'
    
    # Try & vs and (within borough)
    w2 = ward_name.replace(' & ', ' and ')
    match = df_borough[df_borough['Electoral wards and divisions'].str.strip() == w2]
    if len(match) >= 1:
        return match.iloc[0]['Electoral wards and divisions Code'], 'punct'
    
    # Try with borough suffix (within borough range)
    w3 = f"{ward_name} ({borough})"
    match = df_borough[df_borough['Electoral wards and divisions'].str.strip() == w3]
    if len(match) >= 1:
        return match.iloc[0]['Electoral wards and divisions Code'], 'suffix'
    
    # Try the (lad_code, scraped_name) override
    target = OVERRIDES.get((BOROUGH_LA[borough], ward_name))
    if target is not None:
        # Search within borough first
        for candidate in [target, f"{target} ({borough})"]:
            match = df_borough[df_borough['Electoral wards and divisions'].str.strip() == candidate]
            if len(match) >= 1:
                return match.iloc[0]['Electoral wards and divisions Code'], 'fuzzy'
        # Search whole DF if not in borough range
        match = df[df['Electoral wards and divisions'].str.strip() == target]
        if len(match) == 1:
            return match.iloc[0]['Electoral wards and divisions Code'], 'fuzzy-anywhere'

    return None, 'NOT FOUND'


# Load results and Census
with open(DATA / 'all_results.json') as f:
    results = json.load(f)

df = pd.read_excel(SOURCE / 'TS006-Population-Density-2021-wd-ONS.xlsx', sheet_name='Dataset')

mapping = {}  # (borough, ward) -> {gss, match_type}
not_found = []

for borough, wards in results.items():
    for ward in wards:
        code, mtype = find_gss_code(borough, ward, df)
        if code:
            mapping[f"{borough}::{ward}"] = {'gss': code, 'match': mtype}
        else:
            not_found.append((borough, ward))

print(f"Mapped: {len(mapping)} of {sum(len(w) for w in results.values())}")
print(f"NOT FOUND ({len(not_found)}):")
for b, w in not_found:
    print(f"  {b}: {w}")

# Save
with open(DATA / 'all_gss_mapping.json', 'w') as f:
    json.dump(mapping, f, indent=2)

# Print match type distribution
mtypes = {}
for v in mapping.values():
    mtypes[v['match']] = mtypes.get(v['match'], 0) + 1
print(f"\nMatch types: {mtypes}")
