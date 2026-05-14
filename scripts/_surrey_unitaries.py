"""Single source of truth for the two new Surrey unitary authorities first
elected on 7 May 2026. Imported by 22 (Wikipedia fetch) and 23 (results
parser) so they agree without a third coordination file.

Codes are synthetic (XSE, XSW) because ONS has not assigned LAD25 codes —
the unitaries don't take administrative effect until 1 April 2027. The
fourth tuple element lists each unitary's predecessor district WD24 LAD
GSS codes — provenance only, not consumed programmatically (24 splits
LGBCE polygons via the shapefile's District column with hardcoded names,
not codes).
"""

# (code, council_display_name, wiki_article_title, [predecessor LAD GSS codes])
SURREY_UNITARIES = [
    (
        "XSE", "East Surrey", "2026 East Surrey Council election",
        [
            "E07000207",  # Elmbridge
            "E07000208",  # Epsom and Ewell
            "E07000209",  # Mole Valley
            "E07000211",  # Reigate and Banstead
            "E07000215",  # Tandridge
        ],
    ),
    (
        "XSW", "West Surrey", "2026 West Surrey Council election",
        [
            "E07000210",  # Guildford
            "E07000212",  # Runnymede
            "E07000213",  # Spelthorne
            "E07000214",  # Surrey Heath
            "E07000216",  # Waverley
            "E07000217",  # Woking
        ],
    ),
]

# Surrey CC mycouncil moderngov "detailed results by ward" index pages,
# one per unitary. Each lists every ward link as
# mgElectionAreaResults.aspx?XXR=0&ID=<area_id>&RPID=<rpid>. The EID is
# the election ID (49 for XSE, 50 for XSW); the RPID is moderngov's
# session-stable report ID — if Surrey CC ever rotates it, the script
# will 404 on first fetch and the new value can be discovered from
# https://mycouncil.surreycc.gov.uk/mgManageElectionResults.aspx?bcr=1.
SURREY_COUNCIL_INDEX_URLS = {
    "XSE": "https://mycouncil.surreycc.gov.uk/mgElectionElectionAreaResults.aspx?EID=49&RPID=402969917",
    "XSW": "https://mycouncil.surreycc.gov.uk/mgElectionElectionAreaResults.aspx?EID=50&RPID=402969893",
}

# Independent Surrey CC publication of the same results, used as a
# cross-check. The two URLs each render every ward's elected
# candidates so we can assert agreement with mycouncil per-ward.
SURREY_ELECTIONMAP_URLS = {
    "XSE": "https://www10.surreycc.gov.uk/electionmap/EastSurrey/",
    "XSW": "https://www10.surreycc.gov.uk/electionmap/WestSurrey/",
}
