"""One-off discovery probe: which non-GM 2026 councils run on ModernGov?

Issue #36 (Phase 4 / ModernGov slice of #9). Walks every non-GM 2026 council
in data/source/councils.yaml that doesn't yet have `official_url` set, tries
a handful of ModernGov hostname patterns, and reports which respond.

Output is stderr only — review the table, then hand-edit councils.yaml. This
script is NOT part of the runtime 12/13/04c/07d pipeline. It's a discovery
helper that exists so the catalogue lives in version control even though the
output (the yaml edits) is what actually drives the build.

Pattern surveys two host shapes:
  1. <slug>.moderngov.co.uk            — the canonical ModernGov subdomain
  2. democracy.<slug>.gov.uk           — councils that run ModernGov under
                                         their own domain (some do; some
                                         run a different CMS there)

A hit is classified as:
  plain      — plain urllib GET returns 200 with ModernGov HTML markers
  incapsula  — urllib gets blocked or returns an Imperva/Incapsula bounce;
               curl_cffi (via _cloudflare) succeeds with ModernGov markers
  none       — neither host pattern resolves / responds with ModernGov

For each plain/incapsula hit, the probe follows mgManageElectionResults.aspx
and looks for an EID whose anchor text mentions "May 2026" / "7 May 2026" /
"2026". That EID, if found, goes in the table — but only as a hint; the
final yaml triple will use whatever EID the human reviewer confirms.
"""
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / '_official_parsers'))

from _councils import for_region  # noqa: E402

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36 '
      'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)')

GM_LADS = {f'E0800000{i}' for i in range(1, 10)} | {'E08000010'}

# Markers that a returned page is genuinely a ModernGov instance, not a
# generic 404 / landing page on the same host.
MODERNGOV_HTML_RE = re.compile(
    rb'(mgManageElectionResults\.aspx|mgElectionResults\.aspx|moderngov|mg/css/mg\.css|/mgDocLogoLink)',
    re.IGNORECASE,
)

# Imperva/Incapsula challenge fingerprints — same regex 22_fetch_surrey
# uses to detect the bounce.
INCAPSULA_BOUNCE_RE = re.compile(
    rb'_Incapsula_Resource\?(SWUDNSAI|SWJIYLWA)|Request unsuccessful\. Incapsula incident'
)

# EID anchor in the public election-results listing. ModernGov listings link
# via either ID= or EID= — same integer either way — and the title text
# carries the election date (e.g. "County Council, 07/05/2026"). Be lenient
# on the parameter name so we catch both forms.
EID_ANCHOR_RE = re.compile(
    r'<a[^>]+href="mgElectionResults\.aspx\?[^"]*?(?:E?ID)=(\d+)[^"]*"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)
# Fallback: the index sometimes links straight to the per-area page.
EID_ANCHOR_AREA_RE = re.compile(
    r'<a[^>]+href="mgElectionElectionAreaResults\.aspx\?[^"]*?(?:E?ID)=(\d+)[^"]*"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)


def slug_variants(name: str) -> list[str]:
    """Generate plausible ModernGov subdomain slugs for a council name.

    Ordered by likelihood: shortest squashed first, then hyphenated/abbreviated.
    The caller probes each in order and stops at the first 200.
    """
    lower = name.lower()
    squashed = re.sub(r'[^a-z0-9]+', '', lower)
    hyphenated = re.sub(r'[^a-z0-9]+', '-', lower).strip('-')
    variants = [squashed, hyphenated]
    # Hand-pruned alias drops for "and" / "the" / "council" / common geo words
    # that ModernGov instances tend to elide.
    stripped = re.sub(r'\b(and|the|council|district|borough|city|county|of|upon)\b', '', lower)
    stripped_squashed = re.sub(r'[^a-z0-9]+', '', stripped)
    if stripped_squashed and stripped_squashed not in variants:
        variants.append(stripped_squashed)
    # Acronym fallback: first letters of each word (e.g. RBKC, LBBD).
    # 3-5 letters only — 2-letter acronyms are too ambiguous and almost never
    # used as ModernGov subdomains.
    acronym = ''.join(w[0] for w in re.split(r'[^a-z]+', lower) if w)
    if 3 <= len(acronym) <= 5 and acronym not in variants:
        variants.append(acronym)
    # de-dupe but preserve order
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


class DNSMiss(Exception):
    pass


def _urllib_get(url: str, timeout: float = 4.0) -> tuple[int, bytes]:
    """Returns (status, body). Raises DNSMiss when the hostname doesn't
    resolve — caller short-circuits without curl_cffi retry. Other network
    errors return (0, b'')."""
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if hasattr(e, 'read') else b''
    except urllib.error.URLError as e:
        # Surfacing DNS failure means we can skip the curl_cffi fallback —
        # a TLS challenge can't be present on a host that doesn't exist.
        reason = getattr(e, 'reason', None)
        if isinstance(reason, OSError) and reason.errno in (-2, -3, 8) or 'nodename' in str(reason).lower() or 'name or service' in str(reason).lower():
            raise DNSMiss() from e
        return 0, b''
    except Exception:
        return 0, b''


def _curlcffi_get(url: str, timeout: float = 10.0) -> tuple[int, bytes]:
    """Try curl_cffi with Chrome impersonation. Used as a fallback for hosts
    that urllib can't reach (Imperva / Cloudflare TLS challenges)."""
    try:
        from _cloudflare import cloudflare_session
        with cloudflare_session(impersonate='chrome120', timeout=timeout) as s:
            r = s.get(url)
            return r.status_code, r.content
    except Exception:
        return 0, b''


def classify(url: str) -> tuple[str, bytes]:
    """Return (status, body) where status is one of:
       'plain'      — ModernGov HTML reached via urllib
       'incapsula'  — ModernGov HTML reached only via curl_cffi, or urllib body
                      shows Incapsula bounce
       'none'       — host doesn't exist, returns non-200, or isn't ModernGov
    """
    try:
        code, body = _urllib_get(url)
    except DNSMiss:
        return 'none', b''
    if code == 200 and MODERNGOV_HTML_RE.search(body) and not INCAPSULA_BOUNCE_RE.search(body[:2000]):
        return 'plain', body
    # Only fall back to curl_cffi for genuine challenge signals — 403/503 or
    # an Incapsula bounce. A 200 on a non-ModernGov page is just a landing
    # page collision (e.g. democracy.<slug>.gov.uk running a different CMS).
    if INCAPSULA_BOUNCE_RE.search(body[:2000]) or code in (403, 503):
        code2, body2 = _curlcffi_get(url)
        if code2 == 200 and MODERNGOV_HTML_RE.search(body2):
            return 'incapsula', body2
    return 'none', body


def find_2026_eid(host_url: str, body: bytes, *, fetch_via: str) -> tuple[str | None, str | None]:
    """Look for a May-2026 EID either in the body we already have, or via the
    public mgElectionResults.aspx?bcr=1 listing. Returns (eid, title-snippet).
    Date markers like "07/05/2026" or "2026-05-07" count as confirmed May 2026;
    anchors that only mention "2026" without a month are returned as a hint."""
    def scan(text: str) -> tuple[str | None, str | None]:
        confirmed: tuple[str | None, str | None] = (None, None)
        bare_year: tuple[str | None, str | None] = (None, None)
        for rx in (EID_ANCHOR_AREA_RE, EID_ANCHOR_RE):
            for m in rx.finditer(text):
                title = m.group(2).strip()
                title_norm = title.replace('&#47;', '/').replace('&nbsp;', ' ')
                if re.search(r'07[/]05[/]2026|2026-05-07|may\s*2026|7(?:th)?\s*may\s*2026',
                             title_norm, re.IGNORECASE):
                    if confirmed[0] is None:
                        confirmed = (m.group(1), title_norm)
                elif '2026' in title_norm and bare_year[0] is None:
                    bare_year = (m.group(1), title_norm)
        return confirmed if confirmed[0] else bare_year

    text = body.decode('utf-8', errors='replace')
    eid, title = scan(text)
    if eid:
        return eid, title

    # No EID in the landing page — try the public results index.
    parsed = urllib.parse.urlparse(host_url)
    index_url = f'{parsed.scheme}://{parsed.netloc}/mgElectionResults.aspx?bcr=1'
    if fetch_via == 'incapsula':
        code, body2 = _curlcffi_get(index_url)
    else:
        code, body2 = _urllib_get(index_url)
    if code != 200:
        return None, None
    return scan(body2.decode('utf-8', errors='replace'))


def probe_one(council: dict) -> dict:
    """Probe a single council. Returns a dict of result fields. Designed to
    be called from a ThreadPoolExecutor."""
    name = council['name']
    slugs = slug_variants(name)
    host_patterns = []
    for s in slugs:
        host_patterns.append(f'https://{s}.moderngov.co.uk/')
        host_patterns.append(f'https://democracy.{s}.gov.uk/')
    result = {
        'lad_code': council['lad_code'],
        'name': name,
        'status': 'none',
        'host': '',
        'eid': None,
        'title': '',
    }
    for host in host_patterns:
        status, body = classify(host)
        if status in ('plain', 'incapsula'):
            result['status'] = status
            result['host'] = host
            try:
                eid, title = find_2026_eid(host, body, fetch_via=status)
                result['eid'] = eid
                result['title'] = title or ''
            except Exception as e:
                result['title'] = f'(eid-discovery failed: {e!r})'
            return result
    return result


def main():
    candidates = [
        c for c in for_region('gb')
        if c.get('wiki_2026')
        and c['lad_code'] not in GM_LADS
        and not c.get('official_url')
    ]
    print(f'Probing {len(candidates)} non-GM 2026 councils for ModernGov hosting '
          f'(8 concurrent workers)...\n',
          file=sys.stderr, flush=True)
    print(f'{"lad_code":<11} {"name":<38} {"status":<10} {"EID":<6} host  ·  title',
          file=sys.stderr, flush=True)
    print('-' * 120, file=sys.stderr, flush=True)

    tally = {'plain': 0, 'incapsula': 0, 'none': 0}
    hits: list[dict] = []
    by_lad: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(probe_one, c): c for c in candidates}
        for fut in as_completed(futures):
            r = fut.result()
            by_lad[r['lad_code']] = r

    # Print in lad_code order for easier review
    for c in candidates:
        r = by_lad[c['lad_code']]
        tally[r['status']] += 1
        if r['status'] != 'none':
            hits.append(r)
        host_short = urllib.parse.urlparse(r['host']).netloc if r['host'] else '-'
        print(f'{r["lad_code"]:<11} {r["name"][:37]:<38} {r["status"]:<10} '
              f'{(r["eid"] or "-"):<6} {host_short[:30]:<30}  {r["title"][:40]}',
              file=sys.stderr, flush=True)

    print('\n' + '=' * 60, file=sys.stderr, flush=True)
    print(f'Summary:  plain {tally["plain"]}  ·  incapsula {tally["incapsula"]}  ·  '
          f'none {tally["none"]}  (of {len(candidates)})', file=sys.stderr, flush=True)
    print('=' * 60, file=sys.stderr, flush=True)
    if hits:
        print('\nReady-to-paste yaml triples (review EIDs before committing):',
              file=sys.stderr, flush=True)
        for r in hits:
            parser_key = 'moderngov_per_division' if r['status'] == 'plain' else 'moderngov_per_division_incapsula'
            eid_str = r['eid'] or '<TODO>'
            print(f'\n# {r["lad_code"]} {r["name"]} — {r["status"]}', file=sys.stderr, flush=True)
            print(f'  official_url:    "{r["host"]}mgElectionElectionAreaResults.aspx?Page=all&EID={eid_str}"',
                  file=sys.stderr, flush=True)
            print(f'  official_parser: {parser_key}', file=sys.stderr, flush=True)
            print(f'  official_year:   2026', file=sys.stderr, flush=True)
            if r['title']:
                print(f'  # discovered title: {r["title"]}', file=sys.stderr, flush=True)


if __name__ == '__main__':
    main()
