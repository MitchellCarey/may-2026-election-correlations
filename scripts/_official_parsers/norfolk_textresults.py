"""Parse Norfolk County Council 2026 results from elections.norfolk.gov.uk.

Single ASP.NET GridView table at /textresults.aspx, all 84 CEDs on one page.
Each division is introduced by a <th class="divisionHeader" id="division-<slug>">
row, followed by candidate <tr> rows in vote-descending order. The winning row
wraps every cell's text in <strong>…</strong> — used here as the explicit
elected flag rather than relying on row position.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party

extension = 'html'

# Match a winning candidate row: every cell wrapped in <strong>.
# Cells in order: firstname, lastname, party (preceded by colour span),
# division name (from td.divisionColumn), votes.
WINNER_ROW_RE = re.compile(
    r'<td[^>]*headers="division-[^"]+ col-firstname"[^>]*>\s*<strong>([^<]+)</strong>\s*</td>'
    r'\s*<td[^>]*headers="division-[^"]+ col-lastname"[^>]*>\s*<strong>([^<]+)</strong>\s*</td>'
    r'\s*<td[^>]*class="partyColumn"[^>]*>'
        r"\s*<span[^>]*class='party-colour'[^>]*></span>"
        r'\s*<strong>([^<]+)</strong>\s*</td>'
    r'\s*<td[^>]*class="divisionColumn"[^>]*>\s*<strong>([^<]+)</strong>\s*</td>'
    r'\s*<td[^>]*headers="division-[^"]+ col-votes"[^>]*>\s*<strong>(\d+)</strong>\s*</td>',
    re.IGNORECASE | re.DOTALL,
)


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    page = content.decode('utf-8', errors='replace')
    source = urllib.parse.urlparse(council['official_url']).netloc
    out: list[dict] = []
    for m in WINNER_ROW_RE.finditer(page):
        first, last, party_raw, division, votes = (
            html.unescape(g.strip()) for g in m.groups()
        )
        out.append({
            'lad_code':  council['lad_code'],
            'county':    council['name'],
            'division':  division,
            'party':     normalize_party(party_raw),
            'candidate': f'{first} {last}',
            'votes':     int(votes),
            'source':    source,
        })
    return out
