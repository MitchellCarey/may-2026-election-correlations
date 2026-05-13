"""Single source of truth for the 16 Senedd constituency codes + Wikipedia
article titles. Imported by 15 (results parser) and 16 (geometry fetch) so
they agree without a third coordination file.

Codes are synthetic (S01..S16, alphabetical) because there is no
ONS-published Senedd Parliamentary Constituency code in May 2026 — the new
boundaries were finalised by the Democracy and Boundary Commission Cymru
in March 2025 and ONS hasn't shipped an SPC_MAY_2026 lookup yet.
"""

# (code, constituency_name_as_displayed, wiki_article_title)
SENEDD_CONSTITUENCIES = [
    ("S01", "Afan Ogwr Rhondda",                "Afan Ogwr Rhondda"),
    ("S02", "Bangor Conwy Môn",                 "Bangor Conwy Môn"),
    ("S03", "Blaenau Gwent Caerffili Rhymni",   "Blaenau Gwent Caerffili Rhymni"),
    ("S04", "Brycheiniog Tawe Nedd",            "Brycheiniog Tawe Nedd"),
    ("S05", "Caerdydd Ffynnon Taf",             "Caerdydd Ffynnon Taf"),
    ("S06", "Caerdydd Penarth",                 "Caerdydd Penarth"),
    ("S07", "Casnewydd Islwyn",                 "Casnewydd Islwyn"),
    ("S08", "Ceredigion Penfro",                "Ceredigion Penfro"),
    ("S09", "Clwyd",                            "Clwyd (Senedd constituency)"),
    ("S10", "Fflint Wrecsam",                   "Fflint Wrecsam"),
    ("S11", "Gwynedd Maldwyn",                  "Gwynedd Maldwyn"),
    ("S12", "Gŵyr Abertawe",                    "Gŵyr Abertawe"),
    ("S13", "Pen-y-bont Bro Morgannwg",         "Pen-y-bont Bro Morgannwg"),
    ("S14", "Pontypridd Cynon Merthyr",         "Pontypridd Cynon Merthyr"),
    ("S15", "Sir Fynwy Torfaen",                "Sir Fynwy Torfaen"),
    ("S16", "Sir Gaerfyrddin",                  "Sir Gaerfyrddin (Senedd constituency)"),
]
