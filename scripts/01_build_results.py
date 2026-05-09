"""Build ward-level results for all 10 GM boroughs and match to Census GSS codes.

Strategy:
1. Hard-code 2026 winners per ward from extracted data
2. For each ward, find matching GSS code in Census XLSX (with fuzzy fallback for
   boundary-shifted wards in Bolton/Stockport/Trafford)
3. Save consolidated dict: ward_name → {borough, winner, winner_share, gss_code}
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# === 2026 election winners by ward ===
# Format: borough -> {ward: (winner, winner_share_pct or None, turnout_pct or None)}
RESULTS = {
    'Bolton': {
        'Astley Bridge':                    ('Reform', 33.5, None),  # 1635/4886
        'Bradshaw':                         ('Conservative', 36.7, None),  # 1801/4910
        'Breightmet':                       ('Reform', 47.4, None),
        'Bromley Cross':                    ('Conservative', 36.5, None),
        'Farnworth North':                  ('Labour', 28.4, None),
        'Farnworth South':                  ('Reform', 39.7, None),
        'Great Lever':                      ('Labour', 44.0, None),
        'Halliwell':                        ('Green', 42.4, None),
        'Heaton, Lostock & Chew Moor':     ('Conservative', 37.2, None),
        'Horwich North':                    ('Independent', 43.1, None),  # H&BFI
        'Horwich South & Blackrod':         ('Independent', 41.0, None),  # H&BFI
        'Hulton':                           ('Reform', 43.4, None),
        'Kearsley':                         ('Reform', 45.0, None),
        'Little Lever & Darcy Lever':       ('Reform', 50.7, None),
        'Queens Park & Central':            ('Green', 36.4, None),
        'Rumworth':                         ('Green', 47.3, None),
        'Smithills':                        ('LibDem', 39.9, None),
        'Tonge with the Haulgh':            ('Reform', 47.2, None),
        'Westhoughton North & Hunger Hill': ('Reform', 38.7, None),
        'Westhoughton South':               ('Reform', 39.7, None),
    },
    'Bury': {
        'Besses':                           ('Labour', 36.7, None),
        'Bury East':                        ('Labour', 32.4, None),
        'Bury West':                        ('Reform', 35.0, None),
        'Elton':                            ('Reform', 41.5, None),
        'Holyrood':                         ('Labour', 36.7, None),
        # Moorside CANCELLED
        'North Manor':                      ('Labour', 35.0, None),
        'Pilkington Park':                  ('Reform', 35.0, None),
        'Radcliffe East':                   ('Independent', 47.6, None),  # Radcliffe First
        'Radcliffe North & Ainsworth':      ('Reform', 33.4, None),
        'Radcliffe West':                   ('Independent', 38.0, None),  # Radcliffe First
        'Ramsbottom':                       ('Labour', 36.4, None),
        'Redvales':                         ('Other', 30.2, None),  # Workers Party
        'Sedgley':                          ('Labour', 32.4, None),
        "St Mary's":                        ('Labour', 45.5, None),
        'Tottington':                       ('Independent', 51.1, None),
        'Unsworth':                         ('Reform', 33.6, None),
    },
    'Oldham': {
        'Alexandra':                        ('Other', 42.4, 45.01),
        'Chadderton Central':               ('Labour', 32.8, 44.72),
        'Chadderton North':                 ('Reform', 53.5, 47.27),
        'Chadderton South':                 ('Reform', 47.7, 41.80),
        'Coldhurst':                        ('Independent', 45.1, 45.92),
        'Crompton':                         ('Reform', 47.6, 47.76),
        'Failsworth East':                  ('Reform', 58.6, 44.16),
        'Failsworth West':                  ('Reform', 56.1, 42.61),
        'Hollinwood':                       ('Reform', 39.7, 41.80),
        'Medlock Vale':                     ('Labour', 36.6, 40.47),
        'Royton North':                     ('Reform', 58.3, 50.14),
        'Royton South':                     ('Reform', 56.0, 44.80),
        'Saddleworth North':                ('Reform', 41.8, 54.48),
        'Saddleworth South':                ('LibDem', 33.4, 54.77),
        'Saddleworth West & Lees':          ('Reform', 42.2, 49.43),
        'Shaw':                             ('Reform', 47.0, 47.11),
        "St James'":                        ('Reform', 60.6, 39.51),
        "St Mary's":                        ('Other', 50.4, 51.84),  # Oldham Group
        'Waterhead':                        ('Reform', 44.0, 46.09),
        'Werneth':                          ('Labour', 36.0, 51.28),
    },
    'Rochdale': {
        'Balderstone & Kirkholt':           ('Reform', 44.8, 33.46),
        'Bamford':                          ('Conservative', 36.7, 43.37),
        'Castleton':                        ('Reform', 50.0, 37.51),
        'Central Rochdale':                 ('Other', 47.1, 43.91),  # Workers Party
        'East Middleton':                   ('Labour', 36.2, 38.45),
        'Healey':                           ('Reform', 38.5, 43.29),
        'Hopwood Hall':                     ('Reform', 47.2, 36.09),
        'Kingsway':                         ('Labour', 32.7, 40.63),
        'Littleborough Lakeside':           ('Reform', 41.4, 46.18),
        'Milkstone & Deeplish':             ('Other', 49.1, 40.20),  # Workers Party
        'Milnrow & Newhey':                 ('Reform', 39.0, 42.08),
        'Norden':                           ('Conservative', 40.6, 48.48),
        'North Heywood':                    ('Reform', 54.7, 31.60),
        'North Middleton':                  ('Reform', 45.7, 34.77),
        'Smallbridge & Firgrove':           ('LibDem', 30.6, 35.44),
        'South Middleton':                  ('Reform', 45.0, 42.86),
        'Spotland & Falinge':               ('Reform', 31.1, 39.15),
        'Wardle, Shore & West Littleborough':('Reform', 39.7, 43.87),
        'West Heywood':                     ('Reform', 49.3, 33.94),
        'West Middleton':                   ('Reform', 36.6, 30.08),
    },
    'Stockport': {
        'Bramhall North':                   ('LibDem', None, None),
        'Bramhall South & Woodford':        ('LibDem', None, None),
        'Bredbury & Woodley':               ('LibDem', None, None),
        'Bredbury Green & Romiley':         ('LibDem', None, None),
        'Brinnington & Stockport Central':  ('Reform', None, None),
        'Cheadle East & Cheadle Hulme North':('LibDem', None, None),
        'Cheadle Hulme South':              ('LibDem', None, None),  # 3026 Foster-Grime
        'Cheadle West & Gatley':            ('LibDem', None, None),
        'Davenport & Cale Green':           ('LibDem', None, None),
        'Edgeley':                          ('Other', None, None),  # Edgeley Community Assoc
        'Hazel Grove':                      ('LibDem', None, None),
        'Heald Green':                      ('Independent', None, None),
        'Heatons North':                    ('Labour', None, None),
        'Heatons South':                    ('Labour', None, None),
        'Manor':                            ('Reform', None, None),
        'Marple North':                     ('LibDem', None, None),  # 2754 Axon
        'Marple South & High Lane':         ('LibDem', None, None),
        'Norbury & Woodsmoor':              ('LibDem', None, None),
        'Offerton':                         ('LibDem', None, None),  # 1736 Hirst
        'Reddish North':                    ('Green', None, None),
        'Reddish South':                    ('Green', None, None),
    },
    'Tameside': {
        'Ashton Hurst':                     ('Reform', 41.8, 43.05),  # 1410/3744
        "Ashton St Michael's":              ('Reform', 36.5, 37.16),
        'Ashton Waterloo':                  ('Reform', 39.3, 44.49),
        'Audenshaw':                        ('Reform', 42.6, 44.16),
        'Denton North East':                ('Reform', 50.3, 37.49),
        'Denton South':                     ('Reform', 53.6, 37.41),
        'Denton West':                      ('Reform', 49.6, 43.43),
        'Droylsden East':                   ('Reform', 50.1, 39.57),
        'Droylsden West':                   ('Reform', 45.3, None),
        'Dukinfield':                       ('Reform', 48.9, 35.14),
        'Dukinfield/Stalybridge':           ('Reform', 49.6, None),
        'Hyde Godley':                      ('Reform', 36.8, 42.00),
        'Hyde Newton':                      ('Reform', 47.5, 35.60),
        'Hyde Werneth':                     ('Reform', 28.4, 45.20),
        'Longdendale':                      ('Reform', 47.0, 35.30),
        'Mossley':                          ('Reform', 33.3, 46.80),
        "St Peter's":                       ('Labour', 38.7, 38.30),
        'Stalybridge North':                ('Reform', 47.7, 38.90),
        'Stalybridge South':                ('Reform', 35.0, 43.20),
    },
    'Trafford': {
        'Altrincham':                       ('Green', 44.7, 48.64),
        'Ashton upon Mersey':               ('Labour', 34.4, 55.44),
        'Bowdon':                           ('Conservative', 54.6, 56.29),
        'Broadheath':                       ('Conservative', 35.7, 53.73),
        'Brooklands':                       ('Labour', 32.2, 56.60),
        'Bucklow-St Martins':               ('Reform', 44.0, 34.67),
        'Davyhulme':                        ('Reform', 30.1, 48.64),
        'Flixton':                          ('Labour', 29.6, 51.59),
        'Gorse Hill and Cornbrook':         ('Green', 44.6, 35.49),
        'Hale':                             ('Conservative', 45.6, 54.20),
        'Hale Barns and Timperley South':   ('Conservative', 51.9, 54.19),
        'Longford':                         ('Green', 47.0, 44.89),
        'Lostock and Barton':               ('Labour', 31.0, 42.17),
        'Manor':                            ('Conservative', 47.0, 50.55),
        'Old Trafford':                     ('Green', 52.9, 42.19),
        'Sale Central':                     ('Labour', 36.4, 50.12),
        'Sale Moor':                        ('Labour', 36.9, 47.92),
        'Stretford and Humphrey Park':      ('Labour', 32.3, 48.13),
        'Timperley Central':                ('LibDem', 38.9, 50.25),
        'Timperley North':                  ('LibDem', 48.6, 53.40),
        'Urmston':                          ('Labour', 36.3, 49.59),
    },
    'Wigan': {
        'Abram':                            ('Reform', None, None),
        'Ashton-in-Makerfield South':       ('Reform', None, None),
        'Aspull, New Springs & Whelley':    ('Reform', None, None),
        'Astley':                           ('Reform', None, None),
        'Atherton North':                   ('Independent', None, None),
        'Atherton South & Lilford':         ('Reform', None, None),
        'Bryn with Ashton-in-Makerfield North':('Reform', None, None),
        'Douglas':                          ('Reform', None, None),
        'Golborne & Lowton West':           ('Reform', None, None),
        'Hindley':                          ('Reform', None, None),
        'Hindley Green':                    ('Reform', None, None),
        'Ince':                             ('Reform', None, None),
        'Leigh Central & Higher Folds':     ('Reform', None, None),
        'Leigh South':                      ('Reform', None, None),
        'Leigh West':                       ('Reform', None, None),
        'Lowton East':                      ('Reform', None, None),
        'Orrell':                           ('Reform', None, None),
        'Pemberton':                        ('Reform', None, None),
        'Shevington with Lower Ground & Moor':('Reform', None, None),
        'Standish with Langtree':           ('Reform', None, None),
        'Tyldesley & Mosley Common':        ('Reform', None, None),
        'Wigan Central':                    ('Reform', None, None),
        'Wigan West':                       ('Reform', 37.15, None),  # turnout known
        'Winstanley':                       ('Reform', None, None),
        'Worsley Mesnes':                   ('Reform', None, None),
    },
    'Salford': {
        # Most Salford wards are in the legacy combined_wards.json snapshot;
        # Barton & Winton was missed in that extract and is added here so the
        # consolidate step (04) picks it up from all_gm_census.json.
        'Barton & Winton':                  ('Labour', None, None),
    },
}

# Save raw results
DATA.mkdir(parents=True, exist_ok=True)
with open(DATA / 'all_gm_results.json', 'w') as f:
    json.dump(RESULTS, f, indent=2)

total = sum(len(v) for v in RESULTS.values())
print(f"Saved {total} ward results across {len(RESULTS)} boroughs")
for b, w in RESULTS.items():
    party_counts = {}
    for ward, (party, _, _) in w.items():
        party_counts[party] = party_counts.get(party, 0) + 1
    print(f"  {b:>12}: {len(w):>2} wards | {party_counts}")
