"""Per-council parsers for official-source election results.

Each module in this package implements one source pattern (ArcGIS dashboard,
Power BI embed, per-division HTML page, plain text-table, "Declaration of
Poll" PDF, etc.). The dispatcher in scripts/13_extract_official.py looks up
the right module by the `official_parser` key declared on each council in
data/source/councils.yaml.

Module contract — each parser module must export:

    parse(content: bytes, *, council: dict, year: int) -> list[dict]

where `content` is the raw cached fetch from scripts/12_fetch_official_results.py,
`council` is the registry row (so the parser can read lad_code, name, etc.),
and the return value is a list of result rows in the unified schema:

    For E10 (county) councils:
        {'lad_code', 'county', 'division', 'party', 'candidate', 'votes', 'source'}

    For everything else (district / unitary / borough):
        {'lad_code', 'council', 'ward', 'party', 'candidate', 'votes', 'source'}

The `source` field is the URL the row was scraped from (for auditability and
license attribution). Empty until Phase 2 ships the first parser.
"""
