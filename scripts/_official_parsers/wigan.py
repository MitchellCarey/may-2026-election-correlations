"""Parse Wigan Council's bespoke per-ward election results subdomain.

Wigan publishes per-ward results on a dedicated ASP.NET MVC subdomain
(electionresults.wigan.gov.uk) with the URL pattern
    /LocalElections/Home/Index/{election-id}        — index of wards
    /LocalElections/Ward/Index/{ward-id}            — per-ward detail
The 7 May 2026 election is election-id 19 and ward-ids run 455–479.

`official_url` in the registry is the index page. The custom fetch()
walks the index, follows every per-ward link, and caches the combined
response as a single JSON blob keyed by ward name. parse() then walks
each ward's HTML and extracts the row whose result cell contains
<strong>Elected</strong>; losing rows carry an empty <strong></strong>
in that cell.
"""
import html
import json
import re
import time
import urllib.parse
import urllib.request

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'json'

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36 '
      'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)')

WARD_LINK_RE = re.compile(
    r'<a[^>]+href="(/LocalElections/Ward/Index/\d+)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)

ELECTED_ROW_RE = re.compile(
    r'<tr[^>]*>\s*'
    r'<td[^>]*>\s*([^<]+?)\s*</td>\s*'
    r'<td[^>]*>\s*([^<]+?)\s*</td>\s*'
    r'<td[^>]*>\s*([\d,]+)\s*</td>\s*'
    r'<td[^>]*>\s*<strong[^>]*>\s*Elected\s*</strong>\s*</td>',
    re.DOTALL | re.IGNORECASE,
)


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch(url: str, *, council: dict, year: int) -> bytes:
    index_html = _http_get(url).decode('utf-8', errors='replace')
    parsed = urllib.parse.urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}'
    wards: dict[str, str] = {}
    for m in WARD_LINK_RE.finditer(index_html):
        href = m.group(1)
        name = html.unescape(m.group(2).strip())
        if name in wards:
            continue
        time.sleep(0.3)  # be polite
        wards[name] = _http_get(base + href).decode('utf-8', errors='replace')
    return json.dumps({'index_url': url, 'wards': wards}).encode()


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    blob = json.loads(content)
    source = urllib.parse.urlparse(
        blob.get('index_url', council['official_url'])).netloc
    out: list[dict] = []
    for ward_name, page_html in blob.get('wards', {}).items():
        elected = [
            (
                html.unescape(m.group(2).strip()),
                html.unescape(m.group(1).strip()),
                int(m.group(3).replace(',', '')),
            )
            for m in ELECTED_ROW_RE.finditer(page_html)
        ]
        winner = pick_plurality(elected)
        if winner is None:
            continue
        party_raw, candidate, votes = winner
        out.append({
            'lad_code':  council['lad_code'],
            'council':   council['name'],
            'ward':      ward_name,
            'party':     normalize_party(party_raw),
            'candidate': candidate,
            'votes':     votes,
            'source':    source,
        })
    return out
