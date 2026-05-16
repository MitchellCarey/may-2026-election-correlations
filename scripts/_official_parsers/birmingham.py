"""Parse Birmingham City Council 2026 ward results from
birmingham.gov.uk.

The bespoke `/info/50385/election_2026_candidates` (aka `/info/50385/
election_2026_-_results_by_ward`) index links to per-ward subpages at
`/info/50385/election_2026_-_results_by_ward/{N}/{slug}_ward_results_2026`.
Each per-ward page has a 3-col table (Candidate | Party | Vote); the
elected row wraps every cell in `<strong>...</strong>`.
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
    r'<a[^>]+href="(https://www\.birmingham\.gov\.uk/info/50385/election_2026_-_results_by_ward/\d+/[^"]+?)"[^>]*>',
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
    wards: dict[str, str] = {}
    for m in WARD_LINK_RE.finditer(index_html):
        href = m.group(1)
        if href in wards:
            continue
        time.sleep(0.3)
        wards[href] = _http_get(href).decode('utf-8', errors='replace')
    return json.dumps({'index_url': url, 'wards': wards}).encode()


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    blob = json.loads(content)
    source = urllib.parse.urlparse(
        blob.get('index_url', council['official_url'])).netloc
    out: list[dict] = []
    for page_html in blob.get('wards', {}).values():
        h1m = H1_RE.search(page_html)
        if not h1m:
            continue
        ward_name = html.unescape(h1m.group(1).strip())
        # H1 is "Acocks Green Ward results 2026" → strip trailing chrome.
        ward_name = re.sub(r'\s+Ward\s+[Rr]esults\s+\d+\s*$', '',
                           ward_name, flags=re.IGNORECASE)
        elected: list[tuple[str, str, int]] = []
        for rm in ROW_RE.finditer(page_html):
            row = rm.group(1)
            if row.count('<strong') < 3:
                continue
            cells = [_cell_text(c.group(1)) for c in CELL_RE.finditer(row)]
            if len(cells) < 3:
                continue
            try:
                votes = int(cells[2].replace(',', ''))
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
