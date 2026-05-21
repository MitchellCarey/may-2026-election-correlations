"""Registry for the London Assembly overlay (issue #89).

The Assembly is elected alongside the Mayor of London (#81) on a four-year
cycle. The 14 constituency members are elected by FPTP; the remaining 11
"London-wide list" members are allocated by d'Hondt across the entire
Greater London electorate (a single list — unlike Holyrood / Senedd which
split their list seats across multiple electoral regions).

Constituency boundaries have been stable since the GLA's creation in 2000,
so the ONS December 2017 LAC vintage (the only LAC snapshot shipped with
geometry — post-2017 LAC_*_NC datasets carry names and codes only)
describes the geometry used at every target election (2012 / 2016 / 2021
/ 2024). Code prefix `E32` is reserved by ONS for London Assembly
Constituencies.

Per-year Wikipedia articles (`2012_London_Assembly_election` etc.) carry
both the per-constituency FPTP tables and the London-wide list seat
allocation. The per-constituency articles
(`Brent_and_Harrow_(London_Assembly_constituency)` etc.) carry only free
text — no parseable election-box templates — so the consolidated per-year
articles are the only practical Wikipedia source. London Elects PDFs are
the official source for results but PDF parsing is out of scope here;
hand-curation lands via the `gla_assembly_official_<year>.csv` fallback
pattern (mirrors `senedd_official_<year>.csv`).
"""

# (LAC24CD, display name) — ordered alphabetically by code.
# These 14 codes have been stable across every ONS LAC_<MONTH>_<YEAR>
# snapshot since the layer was first published; no boundary review since
# the Assembly's creation in 2000.
GLA_ASSEMBLY_CONSTITUENCIES = [
    ("E32000001", "Barnet and Camden"),
    ("E32000002", "Bexley and Bromley"),
    ("E32000003", "Brent and Harrow"),
    ("E32000004", "City and East"),
    ("E32000005", "Croydon and Sutton"),
    ("E32000006", "Ealing and Hillingdon"),
    ("E32000007", "Enfield and Haringey"),
    ("E32000008", "Greenwich and Lewisham"),
    ("E32000009", "Havering and Redbridge"),
    ("E32000010", "Lambeth and Southwark"),
    ("E32000011", "Merton and Wandsworth"),
    ("E32000012", "North East"),
    ("E32000013", "South West"),
    ("E32000014", "West Central"),
]

# (year, wikipedia article title) — covers every Assembly contest in the
# slider window. 2020 was postponed to 2021 under the Coronavirus
# postponement regulations; no contest exists at that year stop.
GLA_ASSEMBLY_YEARS = [
    (2012, "2012 London Assembly election"),
    (2016, "2016 London Assembly election"),
    (2021, "2021 London Assembly election"),
    (2024, "2024 London Assembly election"),
]

# Single "region" key for the London-wide list seats (one block of 11 seats
# allocated by d'Hondt across all of London — not 11 separate regions).
# Kept as a named constant so the renderer and builder agree on the key.
GLA_ASSEMBLY_REGION_NAME = "Greater London"

# Constituency votes total 14; list votes total 11.
GLA_ASSEMBLY_LIST_SEATS = 11
