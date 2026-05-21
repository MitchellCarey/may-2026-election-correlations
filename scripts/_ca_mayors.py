"""Registry of England's 13 elected Combined-Authority (CA) mayoral regions,
plus one pre-2024 entry for the abolished North of Tyne CA.

Each row is (cauth_code, name, era, wiki_articles_by_year):

- cauth_code is a real ONS CAUTH code (E47*). Codes are stable across the
  two ONS snapshots this layer fetches (December_2023 for North of Tyne,
  December_2025 for the modern set), so no synthetic PRE_ prefix is needed
  — the two code spaces are naturally disjoint (E47000011 was retired when
  the body was abolished; E47000014 is the reformed 7-LAD North East CA).
- era follows the existing CED / Holyrood / Senedd / PCON convention:
    'any'  → always visible (12 stable CAs whose boundary hasn't moved)
    'pre'  → visible only at slider years < 2024 (North of Tyne)
    'post' → visible only at slider years >= 2024 (North East reformed)
  paintAtYear in 07d's renderer hardcodes the 2024 split — see the
  `path.ca-mayor` block.
- wiki_articles_by_year is the per-year per-CA Wikipedia article title
  (canonical pattern "<YYYY> <CA name> mayoral election" — verified live
  for every entry). Used by data/ca_mayors.json's `src` URL and by the
  click-through wiring in 07d.

Imported only by scripts/29 (geometry filtering) and the 07d coverage
report; the election data itself lives in data/ca_mayors.json (hand-
curated, mirroring data/gla_mayor.json shape from issue #81).

Two CAs in the December_2025 snapshot are intentionally excluded from
this registry because they haven't held a mayoral election:
- E47000015 Devon and Torbay (CAA established 2025, no mayor yet)
- E47000018 Lancashire (CCA established 2024, no mayor yet)
"""

# (cauth_code, name, era, wiki_articles_by_year)
CA_MAYORS: list[tuple[str, str, str, dict[int, str]]] = [
    ('E47000001', 'Greater Manchester', 'any', {
        2017: '2017 Greater Manchester mayoral election',
        2021: '2021 Greater Manchester mayoral election',
        2024: '2024 Greater Manchester mayoral election',
    }),
    ('E47000002', 'South Yorkshire', 'any', {
        # Pre-2022 the body was named "Sheffield City Region"; renamed
        # South Yorkshire effective 2022 with no boundary change. The
        # 2018 article uses the old name.
        2018: '2018 Sheffield City Region mayoral election',
        2022: '2022 South Yorkshire mayoral election',
        2024: '2024 South Yorkshire mayoral election',
    }),
    ('E47000003', 'West Yorkshire', 'any', {
        2021: '2021 West Yorkshire mayoral election',
        2024: '2024 West Yorkshire mayoral election',
    }),
    ('E47000004', 'Liverpool City Region', 'any', {
        2017: '2017 Liverpool City Region mayoral election',
        2021: '2021 Liverpool City Region mayoral election',
        2024: '2024 Liverpool City Region mayoral election',
    }),
    ('E47000006', 'Tees Valley', 'any', {
        2017: '2017 Tees Valley mayoral election',
        2021: '2021 Tees Valley mayoral election',
        2024: '2024 Tees Valley mayoral election',
    }),
    ('E47000007', 'West Midlands', 'any', {
        2017: '2017 West Midlands mayoral election',
        2021: '2021 West Midlands mayoral election',
        2024: '2024 West Midlands mayoral election',
    }),
    ('E47000008', 'Cambridgeshire and Peterborough', 'any', {
        # 4-year cycle is 2017 / 2021 / 2025 — no contest in 2024. The issue
        # description's table was inaccurate; verified live against the per-
        # year Wikipedia articles.
        2017: '2017 Cambridgeshire and Peterborough mayoral election',
        2021: '2021 Cambridgeshire and Peterborough mayoral election',
        2025: '2025 Cambridgeshire and Peterborough mayoral election',
    }),
    ('E47000009', 'West of England', 'any', {
        # Same 4-year cycle 2017 / 2021 / 2025. The 2025 contest was also
        # the system's first under FPTP (preceded by Supplementary Vote).
        2017: '2017 West of England mayoral election',
        2021: '2021 West of England mayoral election',
        2025: '2025 West of England mayoral election',
    }),
    ('E47000011', 'North of Tyne', 'pre', {
        # Single contest; body abolished May 2024 + reformed as North East
        # CA (E47000014) with 4 additional LADs (Durham, Gateshead, South
        # Tyneside, Sunderland). Polygon sourced from the December 2023
        # ONS snapshot.
        2019: '2019 North of Tyne mayoral election',
    }),
    ('E47000012', 'York and North Yorkshire', 'any', {
        2024: '2024 York and North Yorkshire mayoral election',
    }),
    ('E47000013', 'East Midlands', 'any', {
        2024: '2024 East Midlands mayoral election',
    }),
    ('E47000014', 'North East', 'post', {
        2024: '2024 North East mayoral election',
    }),
    ('E47000016', 'Hull and East Yorkshire', 'any', {
        2025: '2025 Hull and East Yorkshire mayoral election',
    }),
    ('E47000017', 'Greater Lincolnshire', 'any', {
        2025: '2025 Greater Lincolnshire mayoral election',
    }),
]
