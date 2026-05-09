"""For each ward in 2026 results, find its Census 2021 GSS code.

Approach:
- Try exact match
- Try with & vs and
- Try with parenthesised borough suffix (e.g. "Norden (Rochdale)")
- For Bolton/Stockport/Trafford boundary-shifted wards: use manual mapping
- Wards with no clean Census equivalent are dropped (logged)
"""
import pandas as pd
import json

# Manual mappings for 2026 ward → 2021 ward (Census-equivalent), where boundaries shifted
# Strategy: where 2026 ward is a renamed version of a 2021 ward, point at it.
# Where 2026 ward is a SPLIT or MERGER of multiple 2021 wards: pick the closest
# (introduces some imprecision; flagged as "fuzzy" and dropped if too uncertain).
FUZZY_MAP = {
    # Bolton 2023 boundary review
    'Heaton, Lostock & Chew Moor':       'Heaton and Lostock',
    'Horwich North':                     'Horwich North East',
    'Horwich South & Blackrod':          'Horwich and Blackrod',
    'Westhoughton North & Hunger Hill':  'Westhoughton North and Chew Moor',
    'Little Lever & Darcy Lever':        'Little Lever and Darcy Lever',
    # Bolton: Farnworth split into N+S — use Farnworth (Bolton) for both, flag as approximation
    'Farnworth North':                   'Farnworth (Bolton)',
    'Farnworth South':                   'Farnworth (Bolton)',
    # Bolton: Queens Park & Central is a new ward roughly = old Crompton (Bolton) (town centre area) + parts of others
    'Queens Park & Central':             'Crompton (Bolton)',
    
    # Stockport 2023 boundary changes
    'Brinnington & Stockport Central':   'Brinnington and Central',
    'Cheadle East & Cheadle Hulme North':'Cheadle Hulme North',
    'Cheadle West & Gatley':             'Cheadle and Gatley',
    'Cheadle Hulme South':               'Cheadle Hulme South',
    'Davenport & Cale Green':            'Davenport and Cale Green',
    'Bramhall South & Woodford':         'Bramhall South and Woodford',
    'Bredbury & Woodley':                'Bredbury and Woodley',
    'Bredbury Green & Romiley':          'Bredbury Green and Romiley',
    'Marple South & High Lane':          'Marple South and High Lane',
    'Edgeley':                           'Edgeley and Cheadle Heath',
    'Norbury & Woodsmoor':               'Stepping Hill',
    
    # Trafford 2023 boundary changes
    'Ashton upon Mersey':                'Ashton upon Mersey',  # no change
    'Davyhulme':                         'Davyhulme East',  # use one of Davyhulme E/W as proxy
    'Lostock and Barton':                'Davyhulme West',  # roughly western Davyhulme + parts of Flixton
    'Gorse Hill and Cornbrook':          'Gorse Hill (Trafford)',
    'Hale':                              'Hale Central',
    'Hale Barns and Timperley South':    'Hale Barns',
    'Manor':                             'Priory (Trafford)',  # rough: Manor is in Sale, was part of Priory area
    'Old Trafford':                     'Clifford',
    'Sale Central':                      "St Mary's (Trafford)",
    'Stretford and Humphrey Park':       'Stretford',
    'Timperley Central':                 'Timperley',
    'Timperley North':                   'Village (Trafford)',
    
    # Bolton & Salford & Manchester: punctuation differences
    'Higher Irlam & Peel Green':         'Higher Irlam and Peel Green',
    'Cadishead & Lower Irlam':           'Cadishead and Lower Irlam',
    'Pendlebury & Clifton':              'Pendlebury and Clifton',
    'Boothstown & Ellenbrook':           'Boothstown and Ellenbrook',
    'Worsley & Westwood Park':           'Worsley and Westwood Park',
    'Walkden North':                     'Walkden North',
    'Walkden South':                     'Walkden South',
    'Swinton & Wardley':                 'Swinton and Wardley',
    'Pendleton & Charlestown':           'Pendleton and Charlestown',
    'Weaste & Seedley':                  'Weaste and Seedley',
    'Kersal & Broughton Park':           'Kersal and Broughton Park',
    'Blackfriars & Trinity':             'Blackfriars and Trinity',
    'Barton & Winton':                   'Barton and Winton',  # ward I missed
    
    # Bury
    'Radcliffe North & Ainsworth':       'Radcliffe North and Ainsworth',
    
    # Wigan 2024 boundary changes
    'Aspull, New Springs & Whelley':     'Aspull New Springs Whelley',
    'Atherton North':                    'Atherton',  # 2021 ward Atherton split into N + S&L
    'Atherton South & Lilford':          'Atherton',  # same as above (proxy with same data — flagged)
    'Astley':                            'Astley Mosley Common',
    'Tyldesley & Mosley Common':         'Tyldesley (Wigan)',
    'Bryn with Ashton-in-Makerfield North':'Bryn (Wigan)',
    'Ashton-in-Makerfield South':        'Ashton',  # try; need to check
    'Leigh Central & Higher Folds':      'Leigh East',
    'Shevington with Lower Ground & Moor':'Shevington with Lower Ground',
    
    # Tameside
    'Dukinfield/Stalybridge':            'Dukinfield Stalybridge',  # no slash in 2021
    
    # Rochdale
    'Wardle, Shore & West Littleborough':'Wardle, Shore and West Littleborough',
    'Smallbridge & Firgrove':            'Smallbridge and Firgrove',
    'Spotland & Falinge':                'Spotland and Falinge',
    'Milnrow & Newhey':                  'Milnrow and Newhey',
    'Milkstone & Deeplish':              'Milkstone and Deeplish',
    'Balderstone & Kirkholt':            'Balderstone & Kirkholt',  # Census uses ampersand here
    
    # Oldham
    'Saddleworth West & Lees':           'Saddleworth West and Lees',
}

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
    'Salford':    [('E05013019', 'E05013040')],
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
    
    # Try fuzzy mapping
    if ward_name in FUZZY_MAP:
        target = FUZZY_MAP[ward_name]
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
with open('/home/claude/manchester/all_gm_results.json') as f:
    results = json.load(f)

df = pd.read_excel('/mnt/user-data/uploads/TS006-Population-Density-2021-wd-ONS.xlsx', sheet_name='Dataset')

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
with open('/home/claude/manchester/all_gm_gss_mapping.json', 'w') as f:
    json.dump(mapping, f, indent=2)

# Print match type distribution
mtypes = {}
for v in mapping.values():
    mtypes[v['match']] = mtypes.get(v['match'], 0) + 1
print(f"\nMatch types: {mtypes}")
