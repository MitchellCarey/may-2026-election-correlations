"""Parse a DotNetNuke CMIS-style per-division results index.

CMIS (Committee Management Information System, originally a DNN module by
modgov / OpenElection.net) emits clean RDFa-annotated HTML — each
candidate row carries `property="openelection:elected"` with
`content="True"` on the elected candidate. Used by Essex County Council
2026 results at cmis.essex.gov.uk.

`official_url` is the INDEX page (e.g. .../Elections/.../ViewWards/...).
The parser's custom fetch() walks the per-division links and caches all
HTMLs into one JSON blob; parse() extracts the elected candidate from
each.
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

# Index page: <a title="View 'DIVISION NAME' details" href="...ViewCandidates...">
DIV_LINK_RE = re.compile(
    r'<a\s+title="View &#39;([^&]+)&#39; details"\s+href="([^"]+ViewCandidates[^"]+)"',
    re.IGNORECASE,
)

# Per-candidate row in the per-division page. Each <tr> with
# rel="openelection:candidacy" contains: foaf:name, rdfs:label (party),
# openelection:candidateVoteCount, openelection:elected (True/False).
# `foaf:name` lives in a <span> for first-time candidates but in an <a>
# (linking to the councillor record) for sitting councillors — match either.
CANDIDATE_ROW_RE = re.compile(
    r'<tr[^>]+rel="openelection:candidacy"[^>]*>'
    r'.*?<(?:span|a)[^>]+property="foaf:name"[^>]*>([^<]+)</(?:span|a)>'
    r'.*?<(?:span|a)[^>]+property="rdfs:label"[^>]*>([^<]+)</(?:span|a)>'
    r'.*?<td[^>]+property="openelection:candidateVoteCount"[^>]*>(\d+)</td>'
    r'.*?<td[^>]+property="openelection:elected"[^>]*content="(True|False)"',
    re.DOTALL | re.IGNORECASE,
)

# Sitting-councillor name format: "Cllr <Name> - <Party Group>". Strip
# both the prefix and the trailing " - Group" so the CSV holds the bare
# candidate name (matches first-time-candidate rows).
_CLLR_PREFIX_RE = re.compile(r'^\s*Cllr\s+', re.IGNORECASE)
_GROUP_SUFFIX_RE = re.compile(r'\s*-\s*[^-]+$')


def _clean_name(raw: str) -> str:
    s = _CLLR_PREFIX_RE.sub('', raw)
    s = _GROUP_SUFFIX_RE.sub('', s)
    return s.strip()


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
    divisions: dict[str, str] = {}
    for m in DIV_LINK_RE.finditer(index_html):
        name = html.unescape(m.group(1))
        href = m.group(2)
        div_url = urllib.parse.urljoin(url, href)
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
        winner = None
        for m in CANDIDATE_ROW_RE.finditer(page_html):
            if m.group(4) == 'True':
                winner = {
                    'candidate': _clean_name(html.unescape(m.group(1))),
                    'party':     normalize_party(m.group(2).strip()),
                    'votes':     int(m.group(3)),
                }
                break
        if winner is None:
            continue
        row = {
            'lad_code':  council['lad_code'],
            'party':     winner['party'],
            'candidate': winner['candidate'],
            'votes':     winner['votes'],
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
