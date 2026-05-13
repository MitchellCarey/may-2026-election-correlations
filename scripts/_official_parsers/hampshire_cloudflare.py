"""Parse Hampshire County Council 2026 results from hants.gov.uk.

hants.gov.uk is fronted by Cloudflare and 403s vanilla urllib clients.
This parser uses _cloudflare.cloudflare_session (curl_cffi TLS
impersonation) to get past the challenge, then extracts HCC's
single-table results page.

Page structure (as of 2026-05-13): one HTML page at
`/aboutthecouncil/electionsandvoting/election-results` with a
`<details><table class="table-striped">` block whose `<tbody>` contains
one `<tr><td>Division</td><td>Member</td><td>Party</td></tr>` per
councillor. No per-division detail pages, no vote counts on the page.

Two divisions are 2-member (Fareham Town, Leesland and Town) and
appear twice in the table; both councillors are same-party for 2026, so
the dedup-by-first rule emits one row per division without ambiguity.
Rows where the party column reads "Result awaited" (Aldershot North as
of fetch, count still ongoing) are skipped — the polygon then falls
back to whatever Wikipedia provides, or paints grey.

HCC does not publish vote counts on this page, so rows emit votes=0.
The choropleth in 07d colours polygons by party label, not by vote
count, so this is not load-bearing for the map.
"""
import html
import re
import sys
import urllib.parse

from ._cloudflare import cloudflare_session
from _wiki_parser import normalize_party

extension = 'html'

# Each data row in HCC's results table. Header `<tr>` lives inside a
# `<thead>` so doesn't match this pattern's three-`<td>` shape (the header
# uses `<th>`). Other tables on the page have different cell counts.
ROW_RE = re.compile(
    r'<tr>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*</tr>',
    re.IGNORECASE,
)


def fetch(url: str, *, council: dict, year: int) -> bytes:
    """Single GET of HCC's election-results page via curl_cffi."""
    with cloudflare_session() as s:
        response = s.get(url)
    if response.status_code != 200:
        raise RuntimeError(
            f'Cloudflare bypass returned HTTP {response.status_code} for {url}'
        )
    return response.content


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    page = content.decode('utf-8', errors='replace')
    source = urllib.parse.urlparse(council['official_url']).netloc

    seen: set[str] = set()
    skipped_awaited: list[str] = []
    out: list[dict] = []

    for m in ROW_RE.finditer(page):
        division = html.unescape(m.group(1).strip())
        candidate = html.unescape(m.group(2).strip())
        party_raw = html.unescape(m.group(3).strip())

        if party_raw.lower() == 'result awaited' or candidate.lower() == 'result awaited':
            skipped_awaited.append(division)
            continue
        if division in seen:
            # 2-member division; both councillors same party in 2026.
            continue
        seen.add(division)

        out.append({
            'lad_code':  council['lad_code'],
            'county':    council['name'],
            'division':  division,
            'party':     normalize_party(party_raw),
            'candidate': candidate,
            'votes':     0,
            'source':    source,
        })

    if skipped_awaited:
        print(
            f'  ! Hampshire: skipped {len(skipped_awaited)} division(s) '
            f'with "Result awaited": {", ".join(skipped_awaited)}',
            file=sys.stderr,
        )
    return out
