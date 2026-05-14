"""Parse Devon County Council 2025 results from elections.devon.gov.uk WP REST.

Devon publishes per-division results as `e16_division` custom-post-type
records exposed via the WordPress REST API. The endpoint returns a JSON
array; each post carries the division name in `title.rendered` and the
full candidate list in `candidates[]` (forename, surname, party_group.label,
votes). No explicit "elected" flag — the winner is the candidate with the
highest vote count, picked per division.

The `official_url` includes `?per_page=100` to fetch all 58 divisions in
one request (default per_page=10 paginates across 6 pages). The cache is
the raw JSON response as bytes.
"""
import html
import json
from urllib.parse import urlparse

from _wiki_parser import normalize_party

extension = 'json'


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    divisions = json.loads(content)
    is_county = council['lad_code'].startswith('E10')
    source = urlparse(council['official_url']).netloc

    out: list[dict] = []
    for d in divisions:
        name = html.unescape((d.get('title') or {}).get('rendered', '')).strip()
        candidates = d.get('candidates') or []
        if not name or not candidates:
            continue
        winner = max(candidates, key=lambda c: c.get('votes') or 0)
        forename = (winner.get('candidate_forename') or '').strip()
        surname  = (winner.get('candidate_surname')  or '').strip()
        candidate_name = ' '.join(filter(None, [forename, surname]))
        party_raw = ((winner.get('party_group') or {}).get('label') or '').strip()
        row = {
            'lad_code':  council['lad_code'],
            'party':     normalize_party(party_raw),
            'candidate': candidate_name,
            'votes':     int(winner.get('votes') or 0),
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
