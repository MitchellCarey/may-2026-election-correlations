"""Parse Worcestershire County Council 2025 results from gis.worcestershire.gov.uk.

Worcestershire publishes results via an ArcGIS MapServer layer ("Result
2025", layer 0) with a one-row-per-division schema:

    DIVISION      e.g. "Evesham South"
    ELECTED       winner's name in mixed case (surname uppercased)
    PARTY         party label (e.g. "Reform UK", "Liberal Democrats")
    DISTRICT, ELECTORATE, TURNOUT, ...   metadata

This differs from the ArcGIS FeatureServer schema used by East/West Sussex
(which has per-candidate rows with a `category='Elected Office'` filter),
so we can't reuse `arcgis_dashboard.py`. Worcestershire also doesn't publish
per-candidate vote totals on this layer — rows emit votes=0, matching
hampshire_cloudflare's treatment. The choropleth in 07d colours polygons by
party label, not by vote count, so this is not load-bearing for the map.

The `official_url` is the MapServer /query endpoint with
`?where=1=1&outFields=*&returnGeometry=false&f=json`.
"""
import json
from urllib.parse import urlparse

from _wiki_parser import normalize_party

extension = 'json'


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    data = json.loads(content)
    if data.get('exceededTransferLimit'):
        raise RuntimeError(
            f'ArcGIS query for {council["name"]} {year} hit the transfer limit; '
            f'increase resultRecordCount in official_url or add pagination support')
    features = data.get('features', [])
    is_county = council['lad_code'].startswith('E10')
    source = urlparse(council['official_url']).netloc

    out: list[dict] = []
    for f in features:
        a = f.get('attributes', {})
        division = (a.get('DIVISION') or '').strip()
        elected  = (a.get('ELECTED')  or '').strip()
        party    = (a.get('PARTY')    or '').strip()
        if not division or not elected or not party:
            continue
        row = {
            'lad_code':  council['lad_code'],
            'party':     normalize_party(party),
            'candidate': elected,
            'votes':     0,
            'source':    source,
        }
        if is_county:
            row['county']   = council['name']
            row['division'] = division
        else:
            row['council'] = council['name']
            row['ward']    = division
        out.append(row)
    return out
