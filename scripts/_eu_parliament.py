"""Single source of truth for the 11 GB European Electoral Regions (EERs)
used at the 2014 + 2019 European Parliament elections (issue #91).

The UK was divided into 12 EERs from 1999 until Brexit on 31 January 2020:
9 English Government Office Regions + Scotland + Wales + Northern Ireland.
Northern Ireland is excluded here — NI EP seats were elected under STV
(not d'Hondt) and the GB current map's `gb` viewBox excludes NI anyway,
mirroring how PCON / Holyrood / Senedd handle it.

EER codes are the ONS EER_DEC_2018 set (the boundary set in legal effect
at both 2014 and 2019 — EERs were created in 1999 and unchanged until
the UK left the EU, so a single polygon set serves both contests).

Each per-constituency Wikipedia article (`<Region> (European Parliament
constituency)`) carries `{{Election box begin for list|...}}` blocks for
every contest since the EER was created (1999, 2004, 2009, 2014, 2019)
under H3 `=== YYYY ===` headings inside an `== Election results ==`
H2. One fetch per region yields both target years — mirrors
14b (Senedd) / 17b (Holyrood) / 19b (Westminster) which all use the
single-article-per-constituency pattern. 29's miss report surfaces any
title deviations.

Per-region seat counts at 2014/2019 (sum = 70 GB seats):
  North East England          3   Yorkshire and the Humber   6
  North West England          8   East Midlands              5
  West Midlands               7   East of England            7
  London                      8   South East England        10
  South West England          6   Scotland                   6
  Wales                       4
"""


# (eer_code, display_name, wiki_article_title)
EU_PARLIAMENT_REGIONS = [
    ("E15000001", "North East England",        "North East England (European Parliament constituency)"),
    ("E15000002", "North West England",        "North West England (European Parliament constituency)"),
    ("E15000003", "Yorkshire and the Humber",  "Yorkshire and the Humber (European Parliament constituency)"),
    ("E15000004", "East Midlands",             "East Midlands (European Parliament constituency)"),
    ("E15000005", "West Midlands",             "West Midlands (European Parliament constituency)"),
    ("E15000006", "East of England",           "East of England (European Parliament constituency)"),
    ("E15000007", "London",                    "London (European Parliament constituency)"),
    ("E15000008", "South East England",        "South East England (European Parliament constituency)"),
    ("E15000009", "South West England",        "South West England (European Parliament constituency)"),
    ("S15000001", "Scotland",                  "Scotland (European Parliament constituency)"),
    ("W08000001", "Wales",                     "Wales (European Parliament constituency)"),
]

TARGET_YEARS = (2014, 2019)
