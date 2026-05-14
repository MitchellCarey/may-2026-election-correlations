"""Parse a moderngov-style per-division results index.

The 'moderngov' CMS (run by Modern Mindset Ltd / now ICS) is hosted on
<council>.moderngov.co.uk and exposes:

    Index page:     mgElectionElectionAreaResults.aspx?Page=all&EID=<event_id>
    Per-division:   mgElectionAreaResults.aspx?XXR=0&ID=<area_id>&RPID=<run_id>

`official_url` in the registry is the INDEX page. This parser's custom
fetch() walks the index, follows every per-division link, and caches the
combined response as a single JSON blob keyed by division name. parse()
then walks each division's HTML and extracts the candidate whose outcome
row is marked "Elected".

Used by: West Sussex 2026 (and any other council that lists per-division
results via the same moderngov template).
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
    r'<a[^>]+href="(mgElectionAreaResults\.aspx\?[^"]+)"[^>]+'
    r'title="Link to election area results for ([^"]+)"',
    re.IGNORECASE,
)

# Per-candidate row in the main results table. Marks the elected candidate
# via the "mgMainTxtBold" class on the outcome cell — losers have
# "mgTopText" / "Not elected". The leading <span> is the party-colour swatch.
# The candidate name may be bare text (West Sussex pattern) or wrapped in
# an <a> tag pointing to a sitting councillor's profile (Stockport
# pattern); the optional groups around the name capture either form.
ELECTED_ROW_RE = re.compile(
    r'<td[^>]*class="mgTopText"[^>]*>(?:<span[^>]*>.*?</span>\s*)?'
    r'(?:<a[^>]*>)?\s*([^<]+?)\s*(?:</a>)?\s*</td>\s*'
    r'<td[^>]*class="mgBottomText"[^>]*>([^<]+?)</td>\s*'
    r'<td[^>]*class="mgAlignRightCell"[^>]*>(\d+)</td>\s*'
    r'<td[^>]*class="mgAlignRightCell"[^>]*>[^<]*</td>\s*'
    r'<td[^>]*class="mgMainTxtBold"[^>]*>\s*Elected\s*</td>',
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
    """Fetch the index page, then every per-division page it links to.
    Returns a JSON blob of {'index_url', 'divisions': {name: html, ...}}."""
    index_html = _http_get(url).decode('utf-8', errors='replace')
    # Per-division URLs are relative — resolve against the index URL.
    parsed = urllib.parse.urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}{parsed.path.rsplit("/", 1)[0]}/'
    divisions: dict[str, str] = {}
    for m in DIV_LINK_RE.finditer(index_html):
        href = m.group(1)
        name = html.unescape(m.group(2))
        div_url = urllib.parse.urljoin(base, href)
        time.sleep(0.3)  # be polite
        divisions[name] = _http_get(div_url).decode('utf-8', errors='replace')
    return json.dumps({
        'index_url': url,
        'divisions': divisions,
    }).encode()


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    blob = json.loads(content)
    is_county = council['lad_code'].startswith('E10')
    source = urllib.parse.urlparse(blob.get('index_url', council['official_url'])).netloc
    out: list[dict] = []
    for name, page_html in blob.get('divisions', {}).items():
        m = ELECTED_ROW_RE.search(page_html)
        if not m:
            continue
        candidate = html.unescape(m.group(1).strip())
        party_raw = html.unescape(m.group(2).strip())
        votes = int(m.group(3))
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
