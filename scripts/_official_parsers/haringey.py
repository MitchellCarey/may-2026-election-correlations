"""Parse Haringey Council 2026 ward results from haringey.gov.uk.

The bespoke `/council-elections/elections-voting/local-elections-may-
2026/` index links to per-ward subpages at `/council-elections/elections
-voting/local-elections-may-2026/{slug}-ward`. Each per-ward page has
the results as an `<ul>` of `<li>SURNAME, Forename (Party) – votes:
NNN[, elected: Yes]</li>` items. Elected items are wrapped in
`<strong>...</strong>` and the "elected: Yes" suffix appears inside.
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
    r'<a[^>]+href="(/council-elections/elections-voting/local-elections-may-2026/[^"#]+?-ward)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)

# Elected <li>: <strong>NAME (Party) – votes: NNN, elected: Yes</strong>.
ELECTED_LI_RE = re.compile(
    r'<li[^>]*>\s*<strong[^>]*>\s*'
    r'([^<()]+?)\s*\(\s*([^)]+?)\s*\)\s*[–-]\s*votes:\s*([\d,]+)\s*,\s*elected:\s*Yes'
    r'\s*</strong>\s*</li>',
    re.DOTALL | re.IGNORECASE,
)

H1_RE = re.compile(r'<h1[^>]*>\s*([^<]+?)\s*</h1>', re.IGNORECASE)


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
        time.sleep(0.3)
        wards[name] = _http_get(base + href).decode('utf-8', errors='replace')
    return json.dumps({'index_url': url, 'wards': wards}).encode()


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    blob = json.loads(content)
    source = urllib.parse.urlparse(
        blob.get('index_url', council['official_url'])).netloc
    out: list[dict] = []
    for ward_name, page_html in blob.get('wards', {}).items():
        h1m = H1_RE.search(page_html)
        canonical = html.unescape(h1m.group(1).strip()) if h1m else ward_name
        # Strip trailing " ward" to match WD24 naming.
        canonical = re.sub(r'\s+ward$', '', canonical, flags=re.IGNORECASE)
        elected: list[tuple[str, str, int]] = []
        for lm in ELECTED_LI_RE.finditer(page_html):
            candidate = html.unescape(lm.group(1).strip())
            party_raw = html.unescape(lm.group(2).strip())
            try:
                votes = int(lm.group(3).replace(',', ''))
            except ValueError:
                continue
            elected.append((party_raw, candidate, votes))
        winner = pick_plurality(elected)
        if winner is None:
            continue
        party_raw, candidate, votes = winner
        out.append({
            'lad_code':  council['lad_code'],
            'council':   council['name'],
            'ward':      canonical,
            'party':     normalize_party(party_raw),
            'candidate': candidate,
            'votes':     votes,
            'source':    source,
        })
    return out
