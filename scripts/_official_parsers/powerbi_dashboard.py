"""Parse a Power BI "publish to web" anonymous embed.

Power BI's public embed at `app.powerbi.com/view?r=<token>` exposes its
underlying tabular model over an undocumented JSON-RPC. The `r` query
parameter is a base64-encoded `{"k": <resource_key>, "t": <tenant_id>}`,
and the embed iframe itself fans out to four endpoints on the tenant's
APIM cluster:

    GET  https://wabi-<region>-api.analysis.windows.net/public/routing/cluster/<tenant_id>
    GET  https://wabi-<region>-api.analysis.windows.net/public/reports/<resource_key>/modelsAndExploration?preferReadOnlySession=true
    GET  https://wabi-<region>-api.analysis.windows.net/public/reports/<resource_key>/conceptualschema
    POST https://wabi-<region>-api.analysis.windows.net/public/reports/querydata?synchronous=true

All four use the `X-PowerBI-ResourceKey: <resource_key>` header instead
of a bearer token (anonymous embeds have `powerBIAccessToken = 'any'`).
The cluster's `<region>` (e.g. `uk-south-b-primary`) is discovered by
fetching the embed HTML and reading FixedClusterUri out of the
clusterAssignmentRecord JSON; the APIM hostname is then derived by
swapping `-redirect` for `-api`.

The `querydata` POST takes a SemanticQueryDataShapeCommand naming the
table, columns, and binding to project — modelled on the queries the
embed iframe issues for its own visuals. Responses use Power BI's
dictionary-encoded "DSR" format:

    DS[0].ValueDicts          {D0: [...], D1: [...], ...} per enum column
    DS[0].PH[0].DM0           row array; first entry is a schema header
                              ({S, Ø: all-bits}) establishing the all-null
                              "previous row"
    each subsequent row:
        C  cell values (in column order, skipping reused/null columns)
        R  bitmask — bit i set means "reuse col i from previous row"
        Ø  bitmask — bit i set means "col i is null"

Dictionary-encoded cells carry either an integer index into the named
dict OR the raw string itself (Power BI falls back to inline values
once a column's cardinality outgrows the per-dict cap).

Built for the Esri "Election Results" Power BI template (Suffolk
County Council 2026): a single `Results` table with columns ED,
Candidate, Party Name, Votes, Outcome. Outcome is "Elected" on the
winning row and null otherwise. Other councils on the same template
can register with `official_parser: powerbi_dashboard` and the same
`official_url`; councils on different templates can override the
table + column names via an optional `official_powerbi` block in
the registry.
"""
import base64
import gzip
import json
import re
import urllib.parse
import urllib.request
import zlib

from _wiki_parser import normalize_party

extension = 'json'

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36 '
      'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)')

DEFAULT_TABLE = 'Results'
# Logical key → column name in the data model. Override per-council via
# `official_powerbi.columns` in councils.yaml.
DEFAULT_COLUMNS = {
    'ed':        'ED',
    'candidate': 'Candidate',
    'party':     'Party Name',
    'votes':     'Votes',
    'outcome':   'Outcome',
}
WINNER_OUTCOME = 'Elected'

# Cluster URLs in the public-embed HTML look like
#   "FixedClusterUri":"https://wabi-uk-south-b-primary-redirect.analysis.windows.net/"
_CLUSTER_RE = re.compile(
    r'"FixedClusterUri":"(https://wabi-[a-z0-9-]+-redirect\.analysis\.windows\.net/?)"')


def _http(url: str, *, body: bytes | None = None,
          resource_key: str | None = None) -> bytes:
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Encoding': 'gzip, deflate',
        'ActivityId': '00000000-0000-0000-0000-000000000001',
        'RequestId':  '00000000-0000-0000-0000-000000000002',
        'Origin':     'https://app.powerbi.com',
        'Referer':    'https://app.powerbi.com/',
        'User-Agent': UA,
    }
    if resource_key:
        headers['X-PowerBI-ResourceKey'] = resource_key
    if body is not None:
        headers['Content-Type'] = 'application/json;charset=UTF-8'
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        enc = (r.headers.get('Content-Encoding') or '').lower()
        if enc == 'gzip':
            raw = gzip.decompress(raw)
        elif enc == 'deflate':
            raw = zlib.decompress(raw)
        return raw


def _decode_token(url: str) -> tuple[str, str]:
    q = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(q)
    token = params.get('r', [None])[0]
    if not token:
        raise ValueError(f'no r= parameter in Power BI URL: {url}')
    pad = '=' * (-len(token) % 4)
    blob = json.loads(base64.urlsafe_b64decode(token + pad))
    return blob['k'], blob['t']


def _resolve_apim(view_url: str) -> str:
    """Fetch the embed page, pull FixedClusterUri out of its inline
    clusterAssignmentRecord, and rewrite -redirect → -api (the
    embed JS does the same to get the APIM host)."""
    html = _http(view_url).decode('utf-8', errors='replace')
    m = _CLUSTER_RE.search(html)
    if not m:
        raise RuntimeError(f'no FixedClusterUri in Power BI embed page: {view_url}')
    cluster = m.group(1).rstrip('/')
    return cluster.replace('-redirect.analysis.windows.net',
                           '-api.analysis.windows.net')


def _model_info(apim: str, resource_key: str) -> tuple[str, int]:
    raw = _http(f'{apim}/public/reports/{resource_key}/modelsAndExploration'
                '?preferReadOnlySession=true', resource_key=resource_key)
    obj = json.loads(raw)
    models = obj.get('models') or []
    if not models:
        raise RuntimeError('modelsAndExploration returned no models')
    m = models[0]
    return m['dbName'], m['id']


def _build_payload(dataset_id: str, model_id: int, table: str,
                   cols: dict[str, str]) -> dict:
    order = ('ed', 'candidate', 'party', 'votes', 'outcome')
    select = [{
        'Column': {
            'Expression': {'SourceRef': {'Source': 't'}},
            'Property': cols[k],
        },
        'Name': f'{table}.{k}',
    } for k in order]
    return {
        'version': '1.0.0',
        'queries': [{
            'Query': {'Commands': [{
                'SemanticQueryDataShapeCommand': {
                    'Query': {
                        'Version': 2,
                        'From': [{'Name': 't', 'Entity': table, 'Type': 0}],
                        'Select': select,
                    },
                    'Binding': {
                        'Primary': {'Groupings': [{'Projections': list(range(len(select)))}]},
                        'DataReduction': {'DataVolume': 6,
                                          'Primary': {'Window': {'Count': 30000}}},
                        'Version': 1,
                    },
                }
            }]},
            'QueryId': '',
            'ApplicationContext': {
                'DatasetId': dataset_id,
                'Sources': [{'ReportId': '', 'VisualId': ''}],
            },
        }],
        'cancelQueries': [],
        'modelId': model_id,
    }


def fetch(url: str, *, council: dict, year: int) -> bytes:
    cfg = council.get('official_powerbi') or {}
    table = cfg.get('table', DEFAULT_TABLE)
    cols = {**DEFAULT_COLUMNS, **(cfg.get('columns') or {})}

    resource_key, _tenant_id = _decode_token(url)
    apim = _resolve_apim(url)
    dataset_id, model_id = _model_info(apim, resource_key)
    payload = _build_payload(dataset_id, model_id, table, cols)
    response = _http(f'{apim}/public/reports/querydata?synchronous=true',
                     body=json.dumps(payload).encode(),
                     resource_key=resource_key)
    bundle = {
        'view_url': url,
        'apim': apim,
        'table': table,
        'columns': cols,
        'response': json.loads(response),
    }
    return json.dumps(bundle).encode()


# DSR row decoder. Returns rows in the same column order as the original
# Select (ed, candidate, party, votes, outcome).
def _decode_rows(ds: dict, n_cols: int) -> list[list]:
    out: list[list] = []
    prev = [None] * n_cols
    for i, row in enumerate(ds['PH'][0]['DM0']):
        if i == 0 and 'S' in row:
            prev = [None] * n_cols
            continue
        c = row.get('C', [])
        r_mask = row.get('R', 0)
        null_mask = row.get('Ø', 0)
        cur = list(prev)
        ci = 0
        for j in range(n_cols):
            if (null_mask >> j) & 1:
                cur[j] = None
            elif (r_mask >> j) & 1:
                cur[j] = prev[j]
            else:
                cur[j] = c[ci]
                ci += 1
        out.append(cur)
        prev = cur
    return out


def _resolve(val, dict_name, dicts):
    if val is None or not isinstance(val, int) or not dict_name:
        return val
    return dicts[dict_name][val]


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    bundle = json.loads(content)
    ds = bundle['response']['results'][0]['result']['data']['dsr']['DS'][0]
    dicts = ds.get('ValueDicts', {})
    # Map each Select position to its dictionary name (if dictionary-encoded).
    schema = ds['PH'][0]['DM0'][0]['S']
    dict_for = [sc.get('DN') for sc in schema]
    n_cols = len(schema)  # always 5 for our payload, but read from response

    rows = _decode_rows(ds, n_cols)

    # One row per ED. Multi-seat divisions (rare but possible — Suffolk's
    # Beccles & Kessingland returns two councillors in 2026) keep the
    # top-of-poll elected candidate, matching the convention in the other
    # _official_parsers and the one-color-per-polygon downstream renderer.
    by_ed: dict[str, dict] = {}
    for r in rows:
        outcome = _resolve(r[4], dict_for[4], dicts)
        if outcome != WINNER_OUTCOME:
            continue
        ed = _resolve(r[0], dict_for[0], dicts)
        if not ed:
            continue
        votes = int(r[3] or 0)
        existing = by_ed.get(ed)
        if existing is not None and existing['votes'] >= votes:
            continue
        by_ed[ed] = {
            'candidate': _resolve(r[1], dict_for[1], dicts) or '',
            'party':     _resolve(r[2], dict_for[2], dicts) or '',
            'votes':     votes,
        }

    is_county = council['lad_code'].startswith('E10')
    source = urllib.parse.urlparse(bundle['view_url']).netloc or bundle['view_url']
    out: list[dict] = []
    for ed, rec in by_ed.items():
        row = {
            'lad_code':  council['lad_code'],
            'party':     normalize_party(rec['party']),
            'candidate': rec['candidate'],
            'votes':     rec['votes'],
            'source':    source,
        }
        if is_county:
            row['county']   = council['name']
            row['division'] = ed
        else:
            row['council'] = council['name']
            row['ward']    = ed
        out.append(row)
    return out
