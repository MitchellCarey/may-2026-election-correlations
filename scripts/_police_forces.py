"""Registry of the 41 Police and Crime Commissioner electoral areas in
England and Wales contested across the 2012 / 2016 / 2021 / 2024 cycles.

The four consolidated Wikipedia articles
("<YYYY> England and Wales police and crime commissioner elections")
section each force under a wikilink heading like
``=== [[Avon and Somerset Constabulary]] ===``. The exact wikilink target
varies year-on-year (e.g. "Bedfordshire Police" in 2012 vs "Bedfordshire
Constabulary" in 2016) so each force carries a list of `wiki_aliases`
covering every variant we've observed; the extractor matches each H3
heading against every alias.

ONS PFA codes (E23* in England, W15* in Wales) come from PFA24CD on
``Police_Force_Areas_Dec_2024_EW_BGC`` on the ONS Open Geography Portal.
The 43 PFAs on that layer minus 2 (Metropolitan Police E23000001 and
City of London E23000034 — both London arrangements with no elected
PCC) leaves 41 PCC areas.

``absorbed_from.year`` flags the first PCC cycle from which the force
no longer contests a discrete PCC election (because the role's functions
are exercised by a Combined Authority mayor):

- Greater Manchester (E23000005) — absorbed_from = 2016. Andy Burnham
  took over PCC functions on 8 May 2017, but the May 2016 cycle was
  also skipped in anticipation. The Wikipedia 2016 article explicitly
  notes "there was no election for the Greater Manchester Police as
  the role of police and crime commissioner was due [to be replaced]".
- West Yorkshire (E23000010) — absorbed_from = 2021. Tracy Brabin was
  elected Mayor on 6 May 2021 and took over PCC functions on 10 May
  2021; no WY PCC contest in 2021 or 2024.

South Yorkshire (E23000011) and West Midlands (E23000014) retain
discrete PCC roles through 2024 — the SYMCA and WMCA mayors do not
exercise police functions. (West Midlands' 2024 absorption order was
struck down in the High Court in March 2024 and Simon Foster was
re-elected PCC.) The registry leaves their `absorbed_from` as None.

Forces missing from a given consolidated article (e.g. GM in 2016, WY
in 2021) carry no Election box block, so the extractor naturally
produces no history entry for that (force, year) — no extra plumbing
needed.
"""

POLICE_FORCES: list[tuple[str, str, str, list[str], dict | None]] = [
    # England (37 forces with PCCs — 39 territorial minus MPS and CoLP)
    ('E23000036', 'Avon and Somerset',  'England',
     ['Avon and Somerset Constabulary', 'Avon and Somerset Police'], None),
    ('E23000026', 'Bedfordshire',       'England',
     ['Bedfordshire Police', 'Bedfordshire Constabulary'], None),
    ('E23000023', 'Cambridgeshire',     'England',
     ['Cambridgeshire Constabulary', 'Cambridgeshire Police'], None),
    ('E23000006', 'Cheshire',           'England',
     ['Cheshire Constabulary', 'Cheshire Police'], None),
    ('E23000013', 'Cleveland',          'England',
     ['Cleveland Police'], None),
    ('E23000002', 'Cumbria',            'England',
     ['Cumbria Constabulary', 'Cumbria Police'], None),
    ('E23000018', 'Derbyshire',         'England',
     ['Derbyshire Constabulary', 'Derbyshire Police'], None),
    ('E23000035', 'Devon & Cornwall',   'England',
     ['Devon and Cornwall Police'], None),
    ('E23000039', 'Dorset',             'England',
     ['Dorset Police'], None),
    ('E23000008', 'Durham',             'England',
     ['Durham Constabulary', 'Durham Police'], None),
    ('E23000028', 'Essex',              'England',
     ['Essex Police', 'Essex Constabulary'], None),
    ('E23000037', 'Gloucestershire',    'England',
     ['Gloucestershire Constabulary', 'Gloucestershire Police'], None),
    ('E23000005', 'Greater Manchester', 'England',
     ['Greater Manchester Police'],
     {'year': 2016, 'ca_mayor': 'Mayor of Greater Manchester',
      'ca_mayor_url': 'https://en.wikipedia.org/wiki/Mayor_of_Greater_Manchester'}),
    ('E23000030', 'Hampshire',          'England',
     ['Hampshire Constabulary',
      'Hampshire and Isle of Wight Constabulary'], None),
    ('E23000027', 'Hertfordshire',      'England',
     ['Hertfordshire Constabulary', 'Hertfordshire Police'], None),
    ('E23000012', 'Humberside',         'England',
     ['Humberside Police'], None),
    ('E23000032', 'Kent',               'England',
     ['Kent Police'], None),
    ('E23000003', 'Lancashire',         'England',
     ['Lancashire Constabulary', 'Lancashire Police'], None),
    ('E23000021', 'Leicestershire',     'England',
     ['Leicestershire Constabulary', 'Leicestershire Police'], None),
    ('E23000020', 'Lincolnshire',       'England',
     ['Lincolnshire Police'], None),
    ('E23000004', 'Merseyside',         'England',
     ['Merseyside Police'], None),
    ('E23000024', 'Norfolk',            'England',
     ['Norfolk Constabulary', 'Norfolk Police'], None),
    ('E23000009', 'North Yorkshire',    'England',
     ['North Yorkshire Police'], None),
    ('E23000022', 'Northamptonshire',   'England',
     ['Northamptonshire Constabulary', 'Northamptonshire Police'], None),
    ('E23000007', 'Northumbria',        'England',
     ['Northumbria Police'], None),
    ('E23000019', 'Nottinghamshire',    'England',
     ['Nottinghamshire Police', 'Nottinghamshire Constabulary'], None),
    ('E23000011', 'South Yorkshire',    'England',
     ['South Yorkshire Police'], None),
    ('E23000015', 'Staffordshire',      'England',
     ['Staffordshire Police'], None),
    ('E23000025', 'Suffolk',            'England',
     ['Suffolk Constabulary', 'Suffolk Police'], None),
    ('E23000031', 'Surrey',             'England',
     ['Surrey Police'], None),
    ('E23000033', 'Sussex',             'England',
     ['Sussex Police'], None),
    ('E23000029', 'Thames Valley',      'England',
     ['Thames Valley Police'], None),
    ('E23000017', 'Warwickshire',       'England',
     ['Warwickshire Police'], None),
    ('E23000016', 'West Mercia',        'England',
     ['West Mercia Police'], None),
    ('E23000014', 'West Midlands',      'England',
     ['West Midlands Police'], None),
    ('E23000010', 'West Yorkshire',     'England',
     ['West Yorkshire Police'],
     {'year': 2021, 'ca_mayor': 'Mayor of West Yorkshire',
      'ca_mayor_url': 'https://en.wikipedia.org/wiki/Mayor_of_West_Yorkshire'}),
    ('E23000038', 'Wiltshire',          'England',
     ['Wiltshire Police'], None),

    # Wales (4 forces, all retained PCC roles 2012–2024)
    ('W15000004', 'Dyfed-Powys',        'Wales',
     ['Dyfed-Powys Police', 'Dyfed–Powys Police'], None),
    ('W15000002', 'Gwent',              'Wales',
     ['Gwent Police'], None),
    ('W15000001', 'North Wales',        'Wales',
     ['North Wales Police'], None),
    ('W15000003', 'South Wales',        'Wales',
     ['South Wales Police'], None),
]

PCC_YEARS = (2012, 2016, 2021, 2024)


def wiki_year_title(year: int) -> str:
    """Canonical Wikipedia article title for a consolidated PCC year."""
    return f'{year} England and Wales police and crime commissioner elections'


def alias_to_code() -> dict[str, str]:
    """Flatten the registry into a {wiki_alias: pfa_code} map for the extractor."""
    out: dict[str, str] = {}
    for code, _name, _country, aliases, _absorbed in POLICE_FORCES:
        for a in aliases:
            out[a] = code
    return out
