"""Single source of truth for the 40 pre-2026 Senedd / National Assembly for
Wales constituencies (legal-effect boundaries 2007–2021 / 2026 pre-review)
plus their 5 electoral regions. Imported by 14b (Wikipedia fetcher) and
15b (parser) and 16b (geometry fetch) and 04g (history builder).

The 2026 Senedd review (`_senedd_constituencies.py`) replaced this 40-seat
FPTP layout with a 16-seat closed-list PR layout. Phase 1D of #69 paints
the GB Current map's slider with the pre-review winners (2016 + 2021) on
the geometry that was actually in legal effect at those elections.

Codes are the ONS NAWC21CD set (`W09000001`..`W09000047` — the numeric
range is non-contiguous; 40 of the 47 slots are populated, the other 7
were reallocated during earlier reviews). Discovered via:
  https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/
  NAWC_DEC_2021_WA_BGC_V3/FeatureServer/0

Wikipedia titles follow the uniform `"<Name> (Senedd constituency)"`
pattern (canonical for all 40 — Wikipedia renamed every NAW article to
the Senedd form after the May 2020 institutional rename, even for pre-
2020 contests). 14b's miss report will surface any deviations.

Electoral regions are the 5 PR regions used 2007–2021 for the d'Hondt
top-up seats:
  North Wales              — 9 constituencies + 4 regional list seats
  Mid and West Wales       — 8 constituencies + 4 regional list seats
  South Wales West         — 7 constituencies + 4 regional list seats
  South Wales Central      — 8 constituencies + 4 regional list seats
  South Wales East         — 8 constituencies + 4 regional list seats
Total: 40 + 20 = 60 Members of the Senedd.
"""

# (NAWC21CD, constituency_name_as_displayed, wiki_article_title, electoral_region)
SENEDD_CONSTITUENCIES_2007 = [
    ("W09000022", "Aberavon",                              "Aberavon (Senedd constituency)",                              "South Wales West"),
    ("W09000003", "Aberconwy",                             "Aberconwy (Senedd constituency)",                             "North Wales"),
    ("W09000007", "Alyn and Deeside",                      "Alyn and Deeside (Senedd constituency)",                      "North Wales"),
    ("W09000002", "Arfon",                                 "Arfon (Senedd constituency)",                                 "North Wales"),
    ("W09000038", "Blaenau Gwent",                         "Blaenau Gwent (Senedd constituency)",                         "South Wales East"),
    ("W09000041", "Brecon and Radnorshire",                "Brecon and Radnorshire (Senedd constituency)",                "Mid and West Wales"),
    ("W09000023", "Bridgend",                              "Bridgend (Senedd constituency)",                              "South Wales West"),
    ("W09000035", "Caerphilly",                            "Caerphilly (Senedd constituency)",                            "South Wales East"),
    ("W09000031", "Cardiff Central",                       "Cardiff Central (Senedd constituency)",                       "South Wales Central"),
    ("W09000042", "Cardiff North",                         "Cardiff North (Senedd constituency)",                         "South Wales Central"),
    ("W09000043", "Cardiff South and Penarth",             "Cardiff South and Penarth (Senedd constituency)",             "South Wales Central"),
    ("W09000029", "Cardiff West",                          "Cardiff West (Senedd constituency)",                          "South Wales Central"),
    ("W09000015", "Carmarthen East and Dinefwr",           "Carmarthen East and Dinefwr (Senedd constituency)",           "Mid and West Wales"),
    ("W09000016", "Carmarthen West and South Pembrokeshire", "Carmarthen West and South Pembrokeshire (Senedd constituency)", "Mid and West Wales"),
    ("W09000012", "Ceredigion",                            "Ceredigion (Senedd constituency)",                            "Mid and West Wales"),
    ("W09000009", "Clwyd South",                           "Clwyd South (Senedd constituency)",                           "North Wales"),
    ("W09000004", "Clwyd West",                            "Clwyd West (Senedd constituency)",                            "North Wales"),
    ("W09000026", "Cynon Valley",                          "Cynon Valley (Senedd constituency)",                          "South Wales Central"),
    ("W09000006", "Delyn",                                 "Delyn (Senedd constituency)",                                 "North Wales"),
    ("W09000010", "Dwyfor Meirionnydd",                    "Dwyfor Meirionnydd (Senedd constituency)",                    "Mid and West Wales"),
    ("W09000018", "Gower",                                 "Gower (Senedd constituency)",                                 "South Wales West"),
    ("W09000036", "Islwyn",                                "Islwyn (Senedd constituency)",                                "South Wales East"),
    ("W09000017", "Llanelli",                              "Llanelli (Senedd constituency)",                              "Mid and West Wales"),
    ("W09000044", "Merthyr Tydfil and Rhymney",            "Merthyr Tydfil and Rhymney (Senedd constituency)",            "South Wales East"),
    ("W09000034", "Monmouth",                              "Monmouth (Senedd constituency)",                              "South Wales East"),
    ("W09000011", "Montgomeryshire",                       "Montgomeryshire (Senedd constituency)",                       "Mid and West Wales"),
    ("W09000021", "Neath",                                 "Neath (Senedd constituency)",                                 "South Wales West"),
    ("W09000040", "Newport East",                          "Newport East (Senedd constituency)",                          "South Wales East"),
    ("W09000039", "Newport West",                          "Newport West (Senedd constituency)",                          "South Wales East"),
    ("W09000045", "Ogmore",                                "Ogmore (Senedd constituency)",                                "South Wales West"),
    ("W09000046", "Pontypridd",                            "Pontypridd (Senedd constituency)",                            "South Wales Central"),
    ("W09000014", "Preseli Pembrokeshire",                 "Preseli Pembrokeshire (Senedd constituency)",                 "Mid and West Wales"),
    ("W09000025", "Rhondda",                               "Rhondda (Senedd constituency)",                               "South Wales Central"),
    ("W09000020", "Swansea East",                          "Swansea East (Senedd constituency)",                          "South Wales West"),
    ("W09000019", "Swansea West",                          "Swansea West (Senedd constituency)",                          "South Wales West"),
    ("W09000037", "Torfaen",                               "Torfaen (Senedd constituency)",                               "South Wales East"),
    ("W09000005", "Vale of Clwyd",                         "Vale of Clwyd (Senedd constituency)",                         "North Wales"),
    ("W09000047", "Vale of Glamorgan",                     "Vale of Glamorgan (Senedd constituency)",                     "South Wales Central"),
    ("W09000008", "Wrexham",                               "Wrexham (Senedd constituency)",                               "North Wales"),
    ("W09000001", "Ynys Môn",                              "Ynys Môn (Senedd constituency)",                              "North Wales"),
]

# (region_name, wiki_article_title) — 5 electoral regions, each with a
# single article covering both 2016 + 2021 (and earlier) contests.
# Wikipedia renamed every "(National Assembly for Wales electoral region)"
# article to the Senedd form post-2020; old URLs redirect.
SENEDD_REGIONS_2007 = [
    ("Mid and West Wales",  "Mid and West Wales (Senedd electoral region)"),
    ("North Wales",         "North Wales (Senedd electoral region)"),
    ("South Wales Central", "South Wales Central (Senedd electoral region)"),
    ("South Wales East",    "South Wales East (Senedd electoral region)"),
    ("South Wales West",    "South Wales West (Senedd electoral region)"),
]
