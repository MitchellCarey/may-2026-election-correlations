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
from _official_parsers._pick_winner import pick_plurality

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
# Candidate names may be bare text (West Sussex pattern) or wrapped in an
# <a href="mgUserInfo.aspx?…"> link to a sitting councillor's profile
# (Stockport, Lincoln, Crawley, Milton Keynes, Derbyshire, and most non-WSC
# instances); the optional <a>/</a> groups around the name capture either
# form. Vote counts are tolerant of comma-grouped digits (e.g. "1,476").
ELECTED_ROW_RE = re.compile(
    r'<td[^>]*class="mgTopText"[^>]*>(?:<span[^>]*>.*?</span>\s*)?'
    r'(?:<a[^>]*>)?\s*([^<]+?)\s*(?:</a>)?\s*</td>\s*'
    r'<td[^>]*class="mgBottomText"[^>]*>([^<]+?)</td>\s*'
    r'<td[^>]*class="mgAlignRightCell"[^>]*>([\d,]+)</td>\s*'
    r'(?:<td[^>]*class="mgAlignRightCell"[^>]*>[^<]*</td>\s*)?'
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
    # Optional council-specific prefix strip. Staffordshire labels divisions
    # "Cannock Chase - Brereton and Ravenhill" and Gloucestershire labels
    # them "Cheltenham: All Saints and Oakley" on their moderngov pages, but
    # ONS CED25 names are just the division portion. The yaml field is a
    # regex applied to the left-hand side of each division name.
    strip_re_str = council.get('official_moderngov_strip')
    strip_re = re.compile(strip_re_str) if strip_re_str else None
    out: list[dict] = []
    for name, page_html in blob.get('divisions', {}).items():
        elected = [
            (
                html.unescape(m.group(2).strip()),
                html.unescape(m.group(1).strip()),
                int(m.group(3).replace(',', '')),
            )
            for m in ELECTED_ROW_RE.finditer(page_html)
        ]
        # All-up borough wards elect 2-3 candidates per ward and can return a
        # split slate (e.g. Wandsworth East Putney: 2 Con + 1 Lab). The page
        # is vote-rank ordered so top-of-poll comes first, but that's not
        # always the plurality party — let pick_plurality decide.
        winner = pick_plurality(elected)
        if winner is None:
            continue
        party_raw, candidate, votes = winner
        division = strip_re.sub('', name, count=1) if strip_re else name
        row = {
            'lad_code':  council['lad_code'],
            'party':     normalize_party(party_raw),
            'candidate': candidate,
            'votes':     votes,
            'source':    source,
        }
        if is_county:
            row['county']   = council['name']
            row['division'] = division
        else:
            row['council'] = council['name']
            row['ward']    = division
        out.append(row)
    return out
