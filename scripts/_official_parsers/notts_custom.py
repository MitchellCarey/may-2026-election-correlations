"""Parse Nottinghamshire County Council 2025 results from
electionresults.nottinghamshire.gov.uk.

The custom .NET app at /2025/DetailedResults indexes 56 division pages at
/2025/Divisions/<slug>. Each per-division page has a "Candidates" table
listing every candidate; the elected row has class="elected-row" with
five `<td>` cells: party-colour swatch, name, party (inside <span>s),
formatted votes, share percentage.

`official_url` points at the index page. fetch() walks the index's
division links and caches each per-division HTML into one JSON blob;
parse() extracts the candidate from the second (more detailed) elected-row
on each page — the first occurrence is in a 3-column summary table that
lacks vote totals.
"""
import html
import json
import re
import time
import urllib.parse
import urllib.request

from _wiki_parser import normalize_party

extension = 'json'

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

DIV_LINK_RE = re.compile(
    r'<a\s+href="(/\d{4}/Divisions/[^"]+)"\s+title="Election result for ([^"]+)"',
    re.IGNORECASE,
)

# The detailed candidates table's elected row: party-colour-cell + name +
# party (first <span> reading) + votes (commas) + share. The 3-cell summary
# row higher up the page doesn't match because it has no <td> after the
# party cell.
ELECTED_ROW_RE = re.compile(
    r'<tr\s+class="elected-row">\s*'
    r'<td[^>]*class="party-colour-cell"[^>]*></td>\s*'
    r'<td>([^<]+)</td>\s*'
    r'<td>\s*<span[^>]*>([^<]+)</span>'
    r'.*?<td>([\d,]+)</td>',
    re.DOTALL | re.IGNORECASE,
)


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 '
                      'Safari/537.36 ' + UA,
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch(url: str, *, council: dict, year: int) -> bytes:
    """Fetch the DetailedResults index, then every per-division page."""
    index_html = _http_get(url).decode('utf-8', errors='replace')
    parsed = urllib.parse.urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}'
    divisions: dict[str, str] = {}
    for m in DIV_LINK_RE.finditer(index_html):
        href = m.group(1)
        name = html.unescape(m.group(2))
        if name in divisions:
            continue
        div_url = base + href
        time.sleep(0.3)
        divisions[name] = _http_get(div_url).decode('utf-8', errors='replace')
    return json.dumps({
        'index_url': url,
        'divisions': divisions,
    }).encode()


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    blob = json.loads(content)
    is_county = council['lad_code'].startswith('E10')
    source = urllib.parse.urlparse(
        blob.get('index_url', council['official_url'])).netloc

    out: list[dict] = []
    for name, page_html in blob.get('divisions', {}).items():
        m = ELECTED_ROW_RE.search(page_html)
        if not m:
            continue
        candidate = html.unescape(m.group(1).strip())
        party_raw = html.unescape(m.group(2).strip())
        votes     = int(m.group(3).replace(',', ''))
        row = {
            'lad_code':  council['lad_code'],
            'party':     normalize_party(party_raw),
            'candidate': candidate,
            'votes':     votes,
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
