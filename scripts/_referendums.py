"""Shared registry for the UK-wide nationwide referendums + GE 2010.

Bootstrapped by issue #85 (EU Referendum 2016 LAD-level overlay) and reused
by:
  - #84 (GE 2010 — adds a 4th Westminster history stop on existing
    pcon_geoms_2010.json / ge_history.json plumbing)
  - #86 (Scottish independence referendum 2014 — Yes/No across the 32
    Scottish council areas)
  - #92 (AV referendum 2011 — Yes/No across 439 GB counting areas:
    326 English LADs + 73 Scottish Parliament constituencies +
    40 National Assembly for Wales constituencies; NI's single counting
    area is filtered out, matching the EU Ref `gb` viewBox)

The module exposes two constants:

  REFERENDUMS:        per-event metadata (id, year, title, palette, etc.)
  LAD_2016_TO_2024:   2016 LAD code → 2024 LAD code mapping for the ~37
                       English LADs whose successor district changed
                       (Dorset/BCP 2019, Bucks 2020, N/W Northants 2021,
                       Cumberland/Westmorland & Furness/N Yorkshire/Somerset
                       2023). Forward-looking infrastructure — not load-bearing
                       for #85 because the LAD geometry fetched by 27 is
                       2016-vintage so each 2016 counting area paints on its
                       own polygon. Reserved for tooltip annotations
                       ("now part of …") and for any future view that paints
                       historical referendum results on current LAD geometry.
"""

# Per-referendum metadata. Tuple positions are positional so consumers can
# unpack as (rid, year, title, palette_a, palette_b). palette_a / palette_b
# are hex colours for the two outcomes; both are None for GE 2010 (which
# reuses the standard PARTY_COLOURS palette).
#
# - EU Ref 2016: Leave (purple, recalling the UKIP brand that drove the
#   Leave campaign) vs Remain (yellow, recalling the EU flag's stars).
# - Indyref 2014: Yes (SNP yellow) vs No (Better Together blue).
# - AV Ref 2011: Yes (mid-blue) vs No (red). Distinct from EU Ref's
#   purple/yellow and Indyref's yellow/blue so all three referendum
#   layers stay visually distinct on the GB current map.
REFERENDUMS = [
    ("eu_ref_2016",  2016, "EU Referendum 2016",
     "#552288", "#ffcc00"),                            # Leave / Remain
    ("indyref_2014", 2014, "Scottish independence referendum 2014",
     "#ffcc00", "#0066cc"),                            # Yes / No
    ("av_ref_2011",  2011, "AV Referendum 2011",
     "#1f78b4", "#e31a1c"),                            # AV Yes / AV No
    ("ge_2010",      2010, "UK general election 2010",
     None,      None),
]


# 2016 LAD code → 2024 LAD code that contains its territory today. Covers
# every English LAD reorganisation between 2016 and 2024:
#   * 2019  — Dorset / BCP merger
#   * 2020  — Buckinghamshire UA
#   * 2021  — North + West Northamptonshire
#   * 2023  — Cumberland + Westmorland & Furness, Somerset, North Yorkshire
# Welsh LADs (W06) and Scottish councils (S12) were unchanged across the
# whole window, so they aren't listed here. Use mapping.get(lad16, lad16)
# to resolve any LAD16CD to its current code (unmapped codes are unchanged).
LAD_2016_TO_2024 = {
    # Dorset / BCP (effective 1 April 2019)
    "E06000028": "E06000058",  # Bournemouth       → BCP
    "E06000029": "E06000058",  # Poole             → BCP
    "E07000048": "E06000058",  # Christchurch      → BCP
    "E07000049": "E06000059",  # East Dorset       → Dorset
    "E07000050": "E06000059",  # North Dorset      → Dorset
    "E07000051": "E06000059",  # Purbeck           → Dorset
    "E07000052": "E06000059",  # West Dorset       → Dorset
    "E07000053": "E06000059",  # Weymouth and Portland → Dorset

    # Buckinghamshire (effective 1 April 2020)
    "E07000004": "E06000060",  # Aylesbury Vale    → Buckinghamshire
    "E07000005": "E06000060",  # Chiltern          → Buckinghamshire
    "E07000006": "E06000060",  # South Bucks       → Buckinghamshire
    "E07000007": "E06000060",  # Wycombe           → Buckinghamshire

    # Northamptonshire (effective 1 April 2021)
    "E07000150": "E06000061",  # Corby             → North Northamptonshire
    "E07000152": "E06000061",  # East Northants    → North Northamptonshire
    "E07000153": "E06000061",  # Kettering         → North Northamptonshire
    "E07000156": "E06000061",  # Wellingborough    → North Northamptonshire
    "E07000151": "E06000062",  # Daventry          → West Northamptonshire
    "E07000154": "E06000062",  # Northampton       → West Northamptonshire
    "E07000155": "E06000062",  # South Northants   → West Northamptonshire

    # Cumbria (effective 1 April 2023)
    "E07000026": "E06000063",  # Allerdale         → Cumberland
    "E07000028": "E06000063",  # Carlisle          → Cumberland
    "E07000029": "E06000063",  # Copeland          → Cumberland
    "E07000027": "E06000064",  # Barrow-in-Furness → Westmorland and Furness
    "E07000030": "E06000064",  # Eden              → Westmorland and Furness
    "E07000031": "E06000064",  # South Lakeland    → Westmorland and Furness

    # North Yorkshire (effective 1 April 2023)
    "E07000163": "E06000065",  # Craven            → North Yorkshire
    "E07000164": "E06000065",  # Hambleton         → North Yorkshire
    "E07000165": "E06000065",  # Harrogate         → North Yorkshire
    "E07000166": "E06000065",  # Richmondshire     → North Yorkshire
    "E07000167": "E06000065",  # Ryedale           → North Yorkshire
    "E07000168": "E06000065",  # Scarborough       → North Yorkshire
    "E07000169": "E06000065",  # Selby             → North Yorkshire

    # Somerset (effective 1 April 2023). Note: in 2016, Taunton Deane and
    # West Somerset were still separate (they merged into Somerset West
    # and Taunton in 2019, which itself dissolved into Somerset in 2023),
    # so the 2016 EC CSV uses E07000190 + E07000191, not E07000246.
    "E07000187": "E06000066",  # Mendip            → Somerset
    "E07000188": "E06000066",  # Sedgemoor         → Somerset
    "E07000189": "E06000066",  # South Somerset    → Somerset
    "E07000190": "E06000066",  # Taunton Deane     → Somerset
    "E07000191": "E06000066",  # West Somerset     → Somerset
}


# Sanity check — every value must be a current (2024-era) unitary, and
# every key must be an old (pre-reorganisation) district. The successor
# unitaries E06000058-E06000066 are the only valid targets.
_VALID_SUCCESSORS = {
    "E06000058", "E06000059",                          # BCP, Dorset
    "E06000060",                                       # Buckinghamshire
    "E06000061", "E06000062",                          # N/W Northamptonshire
    "E06000063", "E06000064",                          # Cumberland, W&F
    "E06000065",                                       # North Yorkshire
    "E06000066",                                       # Somerset
}
assert set(LAD_2016_TO_2024.values()) <= _VALID_SUCCESSORS, (
    "LAD_2016_TO_2024 has a successor code outside the 9 reorganised UAs"
)
