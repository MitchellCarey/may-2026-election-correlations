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

from _councils import load as load_councils
from _ward_lookup import wd_codes_for_lad

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
# Council-name -> LAD24CD, sourced from the registry.
COUNCIL_LAD = {c["name"]: c["lad_code"] for c in load_councils()}

def _borough_codes_for(borough):
    """Set of WD24CDs the registry says belong to this council."""
    lad = COUNCIL_LAD.get(borough)
    if lad is None:
        return None  # unknown borough — caller decides how to handle
    return wd_codes_for_lad(lad)


def find_gss_code(borough, ward_name, df):
    """Find GSS code for ward with progressive fallback strategies."""
    codes = _borough_codes_for(borough)
    if codes is None:
        return None, 'UNKNOWN_BOROUGH'
    df_borough = df[df['Electoral wards and divisions Code'].isin(codes)]

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
    target = OVERRIDES.get((COUNCIL_LAD[borough], ward_name))
    if target is not None:
        # Search within borough first. The WD24 lookup is 2024-vintage but the
        # Census XLSX uses 2021 ward codes, so wards whose code changed in the
        # 2023/2024 boundary reviews may fall through to the whole-DF search.
        for candidate in [target, f"{target} ({borough})"]:
            match = df_borough[df_borough['Electoral wards and divisions'].str.strip() == candidate]
            if len(match) >= 1:
                return match.iloc[0]['Electoral wards and divisions Code'], 'fuzzy'
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
