"""Extract all Census 2021 variables for all 161 GSS-mapped wards.

Outputs: all_gm_census.json
  format: {"<Borough>::<Ward>": {gss, density, median_age, pct_18_29, ...}}
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"

# Load the GSS mapping
with open(DATA / 'all_gm_gss_mapping.json') as f:
    mapping = json.load(f)

# Build reverse: gss -> [(borough, ward, match_type)]
gss_to_wards = {}
for key, info in mapping.items():
    borough, ward = key.split('::', 1)
    gss = info['gss']
    if gss not in gss_to_wards:
        gss_to_wards[gss] = []
    gss_to_wards[gss].append({'borough': borough, 'ward': ward, 'match': info['match']})

print(f"Unique GSS codes: {len(gss_to_wards)} (across {len(mapping)} ward entries)")

# Initialize output
out = {}
for key, info in mapping.items():
    out[key] = {'gss': info['gss'], 'match_type': info['match']}

# === TS006: Density ===
print("\n=== TS006 Density ===")
df = pd.read_excel(SOURCE / 'TS006-Population-Density-2021-wd-ONS.xlsx', sheet_name='Dataset')
for key, info in mapping.items():
    row = df[df['Electoral wards and divisions Code'] == info['gss']]
    if len(row):
        out[key]['density'] = float(row.iloc[0]['Observation'])

# === TS007: Age ===
print("=== TS007 Age ===")
df = pd.read_excel(SOURCE / 'TS007-Age-By-Single-Year-2021-wd-ONS.xlsx', sheet_name='Dataset')
print(f"  TS007 cols: {df.columns.tolist()}")
print(f"  Age categories: {df['Age (101 categories)'].unique()[:8]} ... ({df['Age (101 categories)'].nunique()} total)")

# Group by ward, sum populations by age band
def age_band(age_str):
    if age_str == 'Aged under 1 year':
        return 0
    if age_str == 'Aged 100 years and over':
        return 100
    # "Aged 5 years" etc
    parts = age_str.replace('Aged ', '').replace(' years', '').replace(' year', '').strip()
    try:
        return int(parts)
    except:
        return None

df['age_num'] = df['Age (101 categories)'].apply(age_band)

for key, info in mapping.items():
    rows = df[df['Electoral wards and divisions Code'] == info['gss']]
    if len(rows) == 0:
        continue
    total = rows['Observation'].sum()
    if total == 0:
        continue
    # Median age
    rows_sorted = rows.sort_values('age_num')
    cum = 0
    median_age = None
    half = total / 2
    for _, r in rows_sorted.iterrows():
        cum += r['Observation']
        if cum >= half:
            median_age = r['age_num']
            break
    
    # Bands
    under18 = rows[rows['age_num'] < 18]['Observation'].sum()
    a1829 = rows[(rows['age_num'] >= 18) & (rows['age_num'] <= 29)]['Observation'].sum()
    a3049 = rows[(rows['age_num'] >= 30) & (rows['age_num'] <= 49)]['Observation'].sum()
    a5064 = rows[(rows['age_num'] >= 50) & (rows['age_num'] <= 64)]['Observation'].sum()
    a65 = rows[rows['age_num'] >= 65]['Observation'].sum()
    
    out[key]['population'] = int(total)
    out[key]['median_age'] = median_age
    out[key]['pct_under18'] = round(100 * under18 / total, 2)
    out[key]['pct_18_29'] = round(100 * a1829 / total, 2)
    out[key]['pct_30_49'] = round(100 * a3049 / total, 2)
    out[key]['pct_50_64'] = round(100 * a5064 / total, 2)
    out[key]['pct_65plus'] = round(100 * a65 / total, 2)

# === TS063: Occupation (SOC 1-3) ===
print("=== TS063 Occupation ===")
df = pd.read_excel(SOURCE / 'TS063-Occupation-2021-wd-ONS.xlsx', sheet_name='Dataset')
print(f"  TS063 cols: {df.columns.tolist()}")
occ_col = [c for c in df.columns if 'Occupation' in c][0]
occ_code_col = [c for c in df.columns if 'Code' in c and 'Occupation' in c]
print(f"  Categories: {df[occ_col].unique()[:5]}")

for key, info in mapping.items():
    rows = df[df['Electoral wards and divisions Code'] == info['gss']]
    if len(rows) == 0:
        continue
    # Total = "Does not apply" + 9 SOC codes (1-9). We want SOC 1-3 share of all employed.
    # Categories: '0' = Does not apply (out-of-work), 1-9 = SOC categories
    # Or text like "Managers..." - check
    if 'Occupation (current) (10 categories) Code' in df.columns:
        # SOC 1-3 = codes 1, 2, 3
        soc123 = rows[rows['Occupation (current) (10 categories) Code'].isin([1,2,3])]['Observation'].sum()
        # Total in workforce = codes 1-9 (excluding 0 = Does not apply)
        total_workforce = rows[rows['Occupation (current) (10 categories) Code'].isin([1,2,3,4,5,6,7,8,9])]['Observation'].sum()
        if total_workforce > 0:
            out[key]['pct_soc123'] = round(100 * soc123 / total_workforce, 2)

# === TS067: Qualifications ===
print("=== TS067 Qualifications ===")
df = pd.read_excel(SOURCE / 'TS067-Highest-Level-Of-Qualification-2021-wd-ONS.xlsx', sheet_name='Dataset')
print(f"  TS067 cols: {df.columns.tolist()}")
for c in df.columns:
    if 'Code' in c:
        print(f"  {c}: {sorted(df[c].dropna().unique())[:8]}")

# TS067 codes (8-cat): -8=does not apply, 0=No qual, 1=L1+entry, 2=L2, 3=Apprenticeship, 4=L3, 5=L4+, 6=Other
qual_code_col = 'Highest level of qualification (8 categories) Code'
for key, info in mapping.items():
    rows = df[df['Electoral wards and divisions Code'] == info['gss']]
    if len(rows) == 0:
        continue
    # Exclude the -8 'does not apply' rows (these are <16 yo); denom is residents 16+
    valid = rows[rows[qual_code_col] >= 0]
    total = valid['Observation'].sum()
    if total == 0:
        continue
    no_qual = valid[valid[qual_code_col] == 0]['Observation'].sum()
    apprentice = valid[valid[qual_code_col] == 3]['Observation'].sum()
    l4plus = valid[valid[qual_code_col] == 5]['Observation'].sum()
    out[key]['pct_no_qual'] = round(100 * no_qual / total, 2)
    out[key]['pct_apprentice'] = round(100 * apprentice / total, 2)
    out[key]['pct_level4_plus'] = round(100 * l4plus / total, 2)

# === TS054: Tenure ===
print("=== TS054 Tenure ===")
df = pd.read_excel(SOURCE / 'TS054-Tenure-2021-wd-ONS.xlsx', sheet_name='Dataset')
print(f"  TS054 cols: {df.columns.tolist()}")
for c in df.columns:
    if 'Code' in c and 'Tenure' in c:
        print(f"  Codes/values:")
        sample = df[[c, c.replace(' Code', '')]].drop_duplicates().head(10)
        print(sample.to_string())

# TS054 codes (5-cat): 0=Owned, 1=Shared ownership, 2=Social, 3=Private rented, 4=Lives rent free
# Or 8-cat: 0=Owned outright, 1=Owned mortgage, 2=Shared ownership, 3=Social rent council, 4=Social rent other, 5=Private rented (landlord), 6=Private rented (other), 7=Lives rent free
tenure_code_col = [c for c in df.columns if 'Tenure' in c and 'Code' in c][0]
print(f"\n  Using col: {tenure_code_col}")
print(f"  Unique codes: {sorted(df[tenure_code_col].dropna().unique())}")

# Check if codes match what we expect
n_codes = df[tenure_code_col].nunique()
print(f"  Number of unique codes: {n_codes}")

for key, info in mapping.items():
    rows = df[df['Electoral wards and divisions Code'] == info['gss']]
    if len(rows) == 0:
        continue
    total = rows['Observation'].sum()
    if total == 0:
        continue
    # Match Manchester behaviour: owned = codes 0,1,2; social = 3,4; private = 5,6,7
    if n_codes >= 8:
        owned = rows[rows[tenure_code_col].isin([0, 1, 2])]['Observation'].sum()
        social = rows[rows[tenure_code_col].isin([3, 4])]['Observation'].sum()
        private = rows[rows[tenure_code_col].isin([5, 6, 7])]['Observation'].sum()
    else:
        # 5-category: 0=Owned, 1=Shared, 2=Social, 3=Private, 4=rent free
        owned = rows[rows[tenure_code_col].isin([0, 1])]['Observation'].sum()
        social = rows[rows[tenure_code_col] == 2]['Observation'].sum()
        private = rows[rows[tenure_code_col].isin([3, 4])]['Observation'].sum()
    out[key]['pct_owned'] = round(100 * owned / total, 2)
    out[key]['pct_social_rented'] = round(100 * social / total, 2)
    out[key]['pct_private_rented'] = round(100 * private / total, 2)

# === TS004: Country of Birth ===
print("=== TS004 Country of Birth ===")
df = pd.read_excel(SOURCE / 'TS004-Country-Of-Birth-2021-wd-ONS.xlsx', sheet_name='Dataset')
cob_col = [c for c in df.columns if 'Country' in c and 'Code' in c][0]
print(f"  Using col: {cob_col}, unique codes: {sorted(df[cob_col].dropna().unique())}")
# TS004 codes: 1=UK, 2=Ireland, 3=Other EU, 4=Non-EU (varies by category set)
# For 4-category: 1=UK
for key, info in mapping.items():
    rows = df[df['Electoral wards and divisions Code'] == info['gss']]
    if len(rows) == 0:
        continue
    total = rows['Observation'].sum()
    if total == 0:
        continue
    uk_born = rows[rows[cob_col] == 1]['Observation'].sum()
    out[key]['pct_uk_born'] = round(100 * uk_born / total, 2)

# === TS061: Travel to work (WFH) ===
print("=== TS061 WFH ===")
df = pd.read_excel(SOURCE / 'TS061-Method-Used-To-Travel-To-Work-2021-wd-ONS.xlsx', sheet_name='Dataset')
ttw_col = [c for c in df.columns if 'Code' in c and ('Travel' in c or 'Method' in c)][0]
print(f"  Using col: {ttw_col}, unique codes: {sorted(df[ttw_col].dropna().unique())}")
# TS061: 0=Not applicable, 1=WFH (or "mainly works at or from home"), 2-11=various commuting methods
for key, info in mapping.items():
    rows = df[df['Electoral wards and divisions Code'] == info['gss']]
    if len(rows) == 0:
        continue
    # Employed denominator = codes 1-11 (everyone working)
    employed = rows[rows[ttw_col].isin(list(range(1, 12)))]['Observation'].sum()
    if employed == 0:
        continue
    wfh = rows[rows[ttw_col] == 1]['Observation'].sum()
    out[key]['pct_wfh'] = round(100 * wfh / employed, 2)

# === TS008: Sex ===
print("=== TS008 Sex ===")
df = pd.read_excel(SOURCE / 'TS008-Sex-2021-wd-ONS.xlsx', sheet_name='Dataset')
for key, info in mapping.items():
    rows = df[df['Electoral wards and divisions Code'] == info['gss']]
    if len(rows) == 0:
        continue
    f_row = rows[rows['Sex (2 categories)'] == 'Female']
    m_row = rows[rows['Sex (2 categories)'] == 'Male']
    if len(f_row) and len(m_row):
        f = f_row['Observation'].sum()
        m = m_row['Observation'].sum()
        if f + m > 0:
            out[key]['pct_female'] = round(100 * f / (f + m), 2)

# Save
with open(DATA / 'all_gm_census.json', 'w') as f:
    json.dump(out, f, indent=2)

# Stats: how many wards have all expected variables?
expected_vars = ['density', 'median_age', 'pct_18_29', 'pct_65plus', 'pct_soc123',
                 'pct_apprentice', 'pct_level4_plus', 'pct_owned', 'pct_social_rented',
                 'pct_private_rented', 'pct_uk_born', 'pct_wfh', 'pct_female']
counts = {v: 0 for v in expected_vars}
complete = 0
for key, d in out.items():
    if all(v in d for v in expected_vars):
        complete += 1
    for v in expected_vars:
        if v in d:
            counts[v] += 1

print(f"\n=== Coverage ===")
print(f"Wards with all 13 vars: {complete}/{len(out)}")
for v, n in counts.items():
    print(f"  {v}: {n}/{len(out)}")
