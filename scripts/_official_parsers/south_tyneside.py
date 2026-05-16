"""Parse South Tyneside Council 2026 ward results from
portal.southtyneside.info.

The .info portal hosts an ASP.NET app with per-ward subpages at
`Ward.aspx?id={N}`. The index URL
`/elections/LocalGovernment.aspx?id=47` lists every ward link.

Per-ward subpage: 5-col table with class-based markers — the elected
row's cells carry the `bold` CSS class and the 5th cell text is "Yes"
(losers carry `Undec` class with empty 5th cell).
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
    r'<a[^>]+href="(Ward\.aspx\?id=\d+)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)

ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
CELL_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r'<[^>]+>')


def _cell_text(raw: str) -> str:
    return ' '.join(html.unescape(TAG_RE.sub(' ', raw)).split())


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch(url: str, *, council: dict, year: int) -> bytes:
    index_html = _http_get(url).decode('utf-8', errors='replace')
    parsed = urllib.parse.urlparse(url)
    base_url = f'{parsed.scheme}://{parsed.netloc}{parsed.path.rsplit("/", 1)[0]}/'
    wards: dict[str, str] = {}
    for m in WARD_LINK_RE.finditer(index_html):
        href = m.group(1)
        name = html.unescape(m.group(2).strip())
        if name in wards:
            continue
        time.sleep(0.3)
        wards[name] = _http_get(base_url + href).decode('utf-8', errors='replace')
    return json.dumps({'index_url': url, 'wards': wards}).encode()


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    blob = json.loads(content)
    source = urllib.parse.urlparse(
        blob.get('index_url', council['official_url'])).netloc
    out: list[dict] = []
    for ward_name, page_html in blob.get('wards', {}).items():
        # The per-page H1 is always "South Tyneside Council" — the ward
        # name only appears in the index link text (the JSON dict key).
        elected: list[tuple[str, str, int]] = []
        for rm in ROW_RE.finditer(page_html):
            row = rm.group(1)
            cells_raw = list(CELL_RE.finditer(row))
            if len(cells_raw) < 5:
                continue
            cells = [_cell_text(c.group(1)) for c in cells_raw]
            # Elected row: 5th cell text is "Yes" (loser rows are empty).
            if cells[4].strip().lower() != 'yes':
                continue
            try:
                votes = int(cells[3].replace(',', ''))
            except ValueError:
                continue
            elected.append((cells[2], cells[1], votes))
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
