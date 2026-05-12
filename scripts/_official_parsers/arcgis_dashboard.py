"""Parse an ArcGIS Dashboard FeatureServer query response.

The Esri "Election Results Dashboard" solution template publishes results
into a hosted Feature Service with a stable schema:

    contest           e.g. "Election2026_May"      (filtered server-side)
    category          e.g. "Elected Office"        (filtered server-side)
    jurisdictionname  the CED / ward name
    candidate         the candidate's name
    party             the candidate's party (long form, e.g. "Liberal Democrats")
    numvotes          integer vote count
    round             IRV round (always 0 for FPTP)

Several 2026 county councils host their results via this template:
East Sussex, West Sussex. The council's `official_url` in
data/source/councils.yaml is the full FeatureServer/<table>/query URL with
the `contest` and `category` filters baked in, so this parser does no
filtering of its own — it just groups by jurisdictionname and picks the
candidate with the most votes per group.

If `exceededTransferLimit` is true on the response, the query returned
more rows than the layer's maxRecordCount allowed. Bake a higher
`resultRecordCount=N` into the URL, or implement pagination here.
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
    by_ced: dict[str, dict] = {}
    for f in features:
        a = f.get('attributes', {})
        ced = a.get('jurisdictionname')
        if not ced:
            continue
        votes = a.get('numvotes') or 0
        candidate = a.get('candidate', '') or ''
        party_raw = a.get('party', '') or ''
        existing = by_ced.get(ced)
        if existing is None or votes > existing['votes']:
            by_ced[ced] = {
                'candidate': candidate,
                'party':     normalize_party(party_raw),
                'votes':     votes,
            }

    is_county = council['lad_code'].startswith('E10')
    source = urlparse(council['official_url']).netloc or council['official_url']
    out: list[dict] = []
    for ced, rec in by_ced.items():
        row = {
            'lad_code':  council['lad_code'],
            'party':     rec['party'],
            'candidate': rec['candidate'],
            'votes':     rec['votes'],
            'source':    source,
        }
        if is_county:
            row['county']   = council['name']
            row['division'] = ced
        else:
            row['council'] = council['name']
            row['ward']    = ced
        out.append(row)
    return out
