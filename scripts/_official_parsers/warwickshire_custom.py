"""Parse Warwickshire County Council 2025 results from apps.warwickshire.gov.uk.

The custom ASP.NET app at /ElectionResults/elections/2025 embeds the full
per-division winner data in a JavaScript variable on the index page:

    var areas = [ {"type": "FeatureCollection", "features": [
        {"properties": {
            "name":    "Bidford & Welford",
            "party":   "Liberal Democrats",
            "elected": "Cliff Brown",
            ...
        }, "geometry": {...}},
        ...
    ]} ];

The data is a list of one or more GeoJSON FeatureCollections; each feature's
`properties` carries the winner name + party for that division. No
per-candidate vote totals are surfaced here (they live on per-area HTML
pages); rows emit votes=0, matching hampshire_cloudflare's treatment. The
choropleth colours polygons by party label, not by vote count.
"""
import html
import json
import re
from urllib.parse import urlparse

from _wiki_parser import normalize_party

extension = 'html'

VAR_AREAS_RE = re.compile(r'var\s+areas\s*=\s*(\[.*?\]);', re.DOTALL)


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    page = content.decode('utf-8', errors='replace')
    m = VAR_AREAS_RE.search(page)
    if not m:
        raise RuntimeError(
            f'No `var areas = [...]` block found on {council["name"]} {year} '
            f'index page — site structure may have changed')
    feature_collections = json.loads(m.group(1))

    is_county = council['lad_code'].startswith('E10')
    source = urlparse(council['official_url']).netloc

    out: list[dict] = []
    for fc in feature_collections:
        for feat in fc.get('features', []):
            props = feat.get('properties') or {}
            name    = html.unescape((props.get('name')    or '').strip())
            party   = html.unescape((props.get('party')   or '').strip())
            elected = html.unescape((props.get('elected') or '').strip())
            if not name or not party or not elected:
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
                row['division'] = name
            else:
                row['council'] = council['name']
                row['ward']    = name
            out.append(row)
    return out
