"""Single source of truth for the two new Surrey unitary authorities first
elected on 7 May 2026. Imported by 22 (Wikipedia fetch), 23 (results parser)
and 24 (geometry split) so they agree without a third coordination file.

Codes are synthetic (XSE, XSW) because ONS has not assigned LAD25 codes —
the unitaries don't take administrative effect until 1 April 2027. The 11
predecessor districts in each registry tuple's third element are the WD24
LAD GSS codes for the constituent boroughs/districts; 24 uses them to
assign each LGBCE post-review polygon to East or West Surrey via a
centroid-in-WD24-LAD test.
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
