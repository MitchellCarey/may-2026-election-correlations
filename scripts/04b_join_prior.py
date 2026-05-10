"""Join prior winners (data/prior_winners.json) into the 2026 ward dataset.

Adds these fields to each ward in data/gm_all_wards.json:

    prior_party        — string (e.g. 'Labour') or null
    prior_year         — 2022 or 2021, or null
    flipped            — true if winner != prior_party (and both are known)
    match_type_prior   — 'exact', 'norm' (whitespace/punct), 'fuzzy' (manual map),
                         or 'no_prior' (boundary change, no match)

Output: data/gm_all_wards_with_prior.json

Where 2026 ward names don't match prior names directly (common after the 2023
boundary reviews in Bolton/Stockport/Trafford/Wigan), we apply a small manual
mapping. The pattern mirrors scripts/02_match_gss.py's FUZZY_MAP — a few
boundary-shifted wards have no clean 1:1 prior, but for political-control
purposes we map them to the closest predecessor ward.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


# Manual mapping for wards whose 2026 name doesn't match any 2022/2021 prior name
# even after light normalisation. Keyed by (borough, 2026 ward name); value is the
# prior ward name (must exist in data/prior_winners.json under the same borough).
# Where a 2026 ward is a clean rename or near-equivalent of one prior ward, we
# point at it. Where a 2026 ward is a *split* of one prior ward (e.g. Farnworth
# → Farnworth N + S), both children point at the same prior — flagged "fuzzy".
FUZZY_MAP = {
    # Bolton (2023 boundary review)
    ('Bolton', 'Heaton, Lostock & Chew Moor'):  'Heaton & Lostock',
    ('Bolton', 'Horwich North'):                'Horwich North East',
    ('Bolton', 'Horwich South & Blackrod'):     'Horwich & Blackrod',
    ('Bolton', 'Westhoughton North & Hunger Hill'): 'Westhoughton North & Chew Moor',
    ('Bolton', 'Farnworth North'):              'Farnworth',
    ('Bolton', 'Farnworth South'):              'Farnworth',
    ('Bolton', 'Queens Park & Central'):        'Crompton',

    # Stockport (2023 boundary review)
    ('Stockport', 'Brinnington & Stockport Central'):     'Brinnington and Central',
    ('Stockport', 'Cheadle East & Cheadle Hulme North'):  'Cheadle Hulme North',
    ('Stockport', 'Cheadle West & Gatley'):               'Cheadle and Gatley',
    ('Stockport', 'Edgeley'):                             'Edgeley and Cheadle Heath',
    ('Stockport', 'Norbury & Woodsmoor'):                 'Stepping Hill',

    # Trafford (2023 boundary review)
    ('Trafford', 'Davyhulme'):                       'Davyhulme East',
    ('Trafford', 'Lostock and Barton'):              'Davyhulme West',
    ('Trafford', 'Gorse Hill and Cornbrook'):        'Gorse Hill',
    ('Trafford', 'Hale'):                            'Hale Central',
    ('Trafford', 'Hale Barns and Timperley South'):  'Hale Barns',
    ('Trafford', 'Manor'):                           'Priory',
    ('Trafford', 'Old Trafford'):                    'Clifford',
    ('Trafford', 'Sale Central'):                    "St. Mary's",
    ('Trafford', 'Stretford and Humphrey Park'):     'Stretford',
    ('Trafford', 'Timperley Central'):               'Timperley',
    ('Trafford', 'Timperley North'):                 'Village',

    # Wigan (2024 boundary review)
    ('Wigan', 'Ashton-in-Makerfield South'):           'Ashton',
    ('Wigan', 'Bryn with Ashton-in-Makerfield North'): 'Bryn',
    ('Wigan', 'Atherton North'):                       'Atherton',
    ('Wigan', 'Atherton South & Lilford'):             'Atherleigh',
    ('Wigan', 'Astley'):                               'Astley Mosley Common',
    ('Wigan', 'Tyldesley & Mosley Common'):            'Tyldesley',
    ('Wigan', 'Leigh Central & Higher Folds'):         'Leigh East',
    ('Wigan', 'Shevington with Lower Ground & Moor'):  'Shevington with Lower Ground',
}


def normalize_name(name: str) -> str:
    """Loose normalisation for ward-name matching.

    Lowercase; replace " & " with " and "; strip apostrophes, periods,
    and forward slashes; collapse runs of whitespace.
    """
    s = name.lower()
    s = s.replace(' & ', ' and ')
    s = s.replace('/', ' ')
    s = re.sub(r"[\.'’]", '', s)  # strip period, ASCII apostrophe, curly apostrophe
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def main():
    with open(DATA / 'gm_all_wards.json') as f:
        wards = json.load(f)
    with open(DATA / 'prior_winners.json') as f:
        prior = json.load(f)

    # Build per-borough lookup: normalized ward name -> (orig_name, prior_record)
    prior_lookup = {}
    for borough, ward_dict in prior.items():
        prior_lookup[borough] = {
            normalize_name(name): (name, rec)
            for name, rec in ward_dict.items()
        }

    matched_exact = matched_norm = matched_fuzzy = unmatched = 0
    flipped = held = 0
    pending = 0

    for w in wards:
        borough = w['borough']
        ward_name = w['ward']
        bp = prior.get(borough, {})
        bl = prior_lookup.get(borough, {})

        prior_party = None
        prior_year = None
        match_type = 'no_prior'

        # 1. Exact match
        if ward_name in bp:
            rec = bp[ward_name]
            prior_party, prior_year, match_type = rec['prior_party'], rec['prior_year'], 'exact'
            matched_exact += 1
        else:
            # 2. Normalized match
            norm = normalize_name(ward_name)
            if norm in bl:
                _, rec = bl[norm]
                prior_party, prior_year, match_type = rec['prior_party'], rec['prior_year'], 'norm'
                matched_norm += 1
            else:
                # 3. Manual fuzzy mapping
                target = FUZZY_MAP.get((borough, ward_name))
                if target and target in bp:
                    rec = bp[target]
                    prior_party, prior_year, match_type = rec['prior_party'], rec['prior_year'], 'fuzzy'
                    matched_fuzzy += 1
                elif target:
                    # mapping exists but target not found — programmer error
                    print(f'  WARNING: FUZZY_MAP[{borough}, {ward_name}] -> {target!r} not in prior data')
                    unmatched += 1
                else:
                    unmatched += 1

        w['prior_party'] = prior_party
        w['prior_year'] = prior_year
        w['match_type_prior'] = match_type

        winner = w.get('winner')
        if winner == 'Pending' or winner is None:
            w['flipped'] = None
            pending += 1
        elif prior_party is None:
            w['flipped'] = None
        else:
            w['flipped'] = (winner != prior_party)
            if w['flipped']:
                flipped += 1
            else:
                held += 1

    with open(DATA / 'gm_all_wards_with_prior.json', 'w') as f:
        json.dump(wards, f, indent=2)

    total = len(wards)
    print(f'Joined {total} wards:')
    print(f'  matched: exact={matched_exact}, norm={matched_norm}, fuzzy={matched_fuzzy} '
          f'(total {matched_exact + matched_norm + matched_fuzzy})')
    print(f'  unmatched (no_prior): {unmatched}')
    print(f'  pending (no 2026 winner): {pending}')
    print(f'  flipped: {flipped} | held: {held}\n')

    # Summary: flipped TO each party
    flipped_to = {}
    for w in wards:
        if w.get('flipped'):
            flipped_to[w['winner']] = flipped_to.get(w['winner'], 0) + 1
    print('Flipped TO each party:')
    for p, n in sorted(flipped_to.items(), key=lambda x: -x[1]):
        print(f'  {p:>14}: {n:>3}')

    # Surface unmatched ward names so the FUZZY_MAP can be tightened if needed
    if unmatched:
        print('\nUnmatched 2026 wards (no prior found):')
        for w in wards:
            if w['match_type_prior'] == 'no_prior':
                print(f'  {w["borough"]:>12}: {w["ward"]}')


if __name__ == '__main__':
    main()
