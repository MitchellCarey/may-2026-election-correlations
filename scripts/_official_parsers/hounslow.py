"""Parse Hounslow Council 2026 ward results from hounslow.gov.uk.

The bespoke `/elections-voting/local-elections-7-may-2026/8` "Declaration
of results" index links to per-ward subpages at `/elections-voting/
{slug}-declaration-result-poll`.

Per-ward subpage: a table with columns (Name of candidate | Description |
Number of votes*); the elected row's votes cell carries the literal
" (Elected)" suffix after the digits (e.g. "864 (Elected)").
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
    r'<a[^>]+href="(?:https?://[^/"]+)?(/elections-voting/[a-z0-9\-]+-declaration-result-poll)"[^>]*>'
    r'\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)

ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
CELL_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r'<[^>]+>')
H1_RE = re.compile(r'<h1[^>]*>\s*([^<]+?)\s*</h1>', re.IGNORECASE)

ELECTED_VOTES_RE = re.compile(r'^([\d,]+)\s*\(Elected\)\s*$', re.IGNORECASE)


def _cell_text(raw: str) -> str:
    return ' '.join(html.unescape(TAG_RE.sub(' ', raw)).split())


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
        if href in wards:
            continue
        time.sleep(0.3)
        wards[href] = (name, _http_get(base + href).decode('utf-8', errors='replace'))
    # JSON-friendly: store as {href: [name, html]}
    return json.dumps({
        'index_url': url,
        'wards': {h: [n, html] for h, (n, html) in wards.items()},
    }).encode()


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    blob = json.loads(content)
    source = urllib.parse.urlparse(
        blob.get('index_url', council['official_url'])).netloc
    out: list[dict] = []
    for href, (link_name, page_html) in blob.get('wards', {}).items():
        h1m = H1_RE.search(page_html)
        if h1m:
            # H1 is e.g. "Hounslow East - Declaration of result of poll"
            heading = html.unescape(h1m.group(1).strip())
            ward_name = re.split(r'\s*-\s*Declaration of result of poll\s*$',
                                  heading, flags=re.IGNORECASE)[0].strip()
        else:
            ward_name = link_name
        elected: list[tuple[str, str, int]] = []
        for rm in ROW_RE.finditer(page_html):
            cells = [_cell_text(c.group(1)) for c in CELL_RE.finditer(rm.group(1))]
            if len(cells) < 3:
                continue
            vm = ELECTED_VOTES_RE.match(cells[2])
            if not vm:
                continue
            try:
                votes = int(vm.group(1).replace(',', ''))
            except ValueError:
                continue
            elected.append((cells[1], cells[0], votes))
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
