"""Parse Huntingdonshire District Council 2026 ward results from
huntingdonshire.gov.uk.

The bespoke `/election-2026/may-2026-election-results/` page hosts a
summary table linking out to per-ward subpages. The richer per-ward
subpage carries the full breakdown (with votes), so this parser walks
the index and bundles every per-ward page as a JSON cache (mirroring
wigan.py).

Per-ward subpage: `<table id="ward-result-table">` with 5 columns
(Logo | Party | Candidate Name | Votes | Elected); the elected row
carries `<td class="elected-cell">Elected</td>`.
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
    r'<a[^>]+href="(/election-2026/may-2026-election-results/[^/"]+/?)"[^>]*>'
    r'\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)

ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
CELL_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r'<[^>]+>')
H1_RE = re.compile(r'<h1[^>]*>\s*([^<]+?)\s*</h1>', re.IGNORECASE)


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
        # Some links carry the long form ("St. Ives East Ward"); the H1
        # on the page is canonical, prefer it when available.
        h1m = H1_RE.search(page_html)
        canonical = html.unescape(h1m.group(1).strip()) if h1m else ward_name
        elected: list[tuple[str, str, int]] = []
        for rm in ROW_RE.finditer(page_html):
            row = rm.group(1)
            cells = [_cell_text(c.group(1)) for c in CELL_RE.finditer(row)]
            if not cells:
                continue
            # 5-col layout: [logo, party, candidate, votes, "Elected"/""]
            if len(cells) < 5 or cells[-1].lower() != 'elected':
                continue
            try:
                votes = int(cells[3].replace(',', ''))
            except ValueError:
                continue
            elected.append((cells[1], cells[2], votes))
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
