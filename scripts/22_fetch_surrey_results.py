"""Fetch results for the two 2026 Surrey unitary elections (East Surrey,
West Surrey) from two sources:

  1. Wikipedia per-unitary articles — primary fallback for any ward
     mycouncil hasn't yet published.
  2. Surrey CC mycouncil moderngov per-ward pages — primary source for
     the per-ward winners (issue #42 fills the 22 wards still pending
     on Wikipedia).
  3. Surrey CC electionmap app — independent rendering of the same
     data, used by 23 to cross-check every ward against mycouncil.

Counterpart to scripts/14_fetch_senedd_results.py — the Surrey unitaries
don't have ONS LAD codes (administrative effect 1 April 2027) and so
don't fit the per-council registry in councils.yaml. The list of articles
and the mycouncil/electionmap URLs all live in
scripts/_surrey_unitaries.py.

Output (all idempotent — files already present are skipped):
  data/source/wiki_surrey_<slug>_2026.json    — Wikipedia
  data/source/surrey_council_index_<EID>.html — mycouncil detailed-by-ward index
  data/source/surrey_council_ward_<ID>.html   — mycouncil per-ward
  data/source/surrey_electionmap_<XSE|XSW>.html — Surrey CC electionmap
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# scripts/_official_parsers is the only sibling subpackage; the bare 'scripts'
# directory is added to sys.path implicitly when running these as __main__,
# but the parsers subpackage isn't, so reach into it explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent / '_official_parsers'))
from _cloudflare import cloudflare_session  # noqa: E402

from _surrey_unitaries import (  # noqa: E402
    SURREY_COUNCIL_INDEX_URLS,
    SURREY_ELECTIONMAP_URLS,
    SURREY_UNITARIES,
)

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
API = 'https://en.wikipedia.org/w/api.php'

TITLES = [t for (_c, _n, t, _d) in SURREY_UNITARIES]

# moderngov per-ward link in the detailed-by-ward index page. Same shape
# we already parse in scripts/_official_parsers/moderngov_per_division.py.
DIV_LINK_RE = re.compile(
    r'<a[^>]+href="(mgElectionAreaResults\.aspx\?[^"]+)"',
    re.IGNORECASE,
)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def fetch(title: str) -> dict:
    qs = urllib.parse.urlencode({
        'action': 'parse',
        'page': title,
        'format': 'json',
        'formatversion': '2',
        'prop': 'wikitext',
        'redirects': '1',
    })
    req = urllib.request.Request(f'{API}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fetch_wikipedia() -> tuple[int, int, list[str]]:
    fetched = skipped = 0
    misses: list[str] = []
    for title in TITLES:
        out = SOURCE / f'wiki_surrey_{slug(title)}_2026.json'
        if out.exists():
            skipped += 1
            continue
        print(f'Fetching {title}...')
        data = fetch(title)
        if 'error' in data:
            print(f'  ! {data["error"].get("code")}: {data["error"].get("info", "")}')
            misses.append(title)
            time.sleep(0.5)
            continue
        out.write_text(json.dumps(data))
        fetched += 1
        time.sleep(0.5)  # be nice to Wikipedia
    return fetched, skipped, misses


INCAPSULA_BOUNCE_RE = re.compile(
    rb'_Incapsula_Resource\?(SWUDNSAI|SWJIYLWA)|Request unsuccessful\. Incapsula incident'
)


def _is_incapsula_bounce(content: bytes) -> bool:
    """The Imperva/Incapsula JS-challenge response comes in two shapes:
    (a) 212-byte stub with `_Incapsula_Resource?SWJIYLWA=...` script tag;
    (b) ~900-byte iframe-redirect with `_Incapsula_Resource?SWUDNSAI=...`.
    Either way it has no useful content; detect both so we retry/sentinel."""
    return bool(INCAPSULA_BOUNCE_RE.search(content[:2000]))


def _session_get(session, url: str, referer: str | None = None) -> bytes:
    """GET via a curl_cffi session, raising on non-200 or Incapsula bounce.
    mycouncil.surreycc.gov.uk is fronted by Incapsula/Imperva; www10 is
    not, but routing both through the same path keeps the code uniform."""
    headers = {'Referer': referer} if referer else {}
    response = session.get(url, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f'HTTP {response.status_code} for {url}')
    if _is_incapsula_bounce(response.content):
        raise RuntimeError(f'Incapsula bounce for {url}')
    return response.content


# curl_cffi 0.7 ships these chrome-family TLS fingerprints; rotating
# across requests defeats Incapsula's per-fingerprint adaptive scoring.
IMPERSONATIONS = ['chrome120', 'chrome116', 'chrome119', 'chrome124', 'edge101']


def _fetch_with_retry(url: str, referer: str | None = None,
                      *, max_attempts: int = 3) -> bytes:
    """Open a fresh cloudflare_session per attempt with a rotating
    impersonation profile. mycouncil.surreycc.gov.uk's Incapsula tier
    rate-limits bursts from a single IP regardless of fingerprint; long
    backoffs don't help because the block is keyed on recent request
    volume. Three quick tries then give up — partial coverage is OK
    because 23_extract_surrey.py falls back to Wikipedia on cache miss."""
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        impersonate = IMPERSONATIONS[(attempt - 1) % len(IMPERSONATIONS)]
        try:
            with cloudflare_session(impersonate=impersonate) as s:
                return _session_get(s, url, referer=referer)
        except RuntimeError as e:
            last_err = e
            if attempt < max_attempts:
                backoff = 5.0 * attempt
                print(f'  ! attempt {attempt}/{max_attempts} ({impersonate}): {e}; '
                      f'sleeping {backoff:.0f}s', file=sys.stderr)
                time.sleep(backoff)
            else:
                print(f'  ! attempt {attempt}/{max_attempts} ({impersonate}): {e}',
                      file=sys.stderr)
    raise RuntimeError(f'Gave up after {max_attempts} attempts: {last_err}')


# Sentinel content written when Incapsula blocks repeatedly. Future runs
# detect this marker and skip the URL so we don't hammer the rate-limit
# tier on every pipeline re-run. To force a retry, delete the file.
FAILED_SENTINEL = (
    b'<!-- gm-2026-ward-analysis: mycouncil fetch failed (Incapsula rate-limited). '
    b'Delete this file to retry. 23_extract_surrey.py treats it as missing data. -->\n'
)


def _is_failed_sentinel(content: bytes) -> bool:
    return content.startswith(b'<!-- gm-2026-ward-analysis: mycouncil fetch failed')


def _cached_or_fetch(path: Path, url: str, *, label: str,
                     referer: str | None = None,
                     post_delay: float = 2.0) -> str:
    """Return one of 'cached', 'fetched', 'failed', 'sentinel'. Treats
    a cached Incapsula bounce as if the file didn't exist (re-fetches).
    Treats a failed-sentinel cache as 'sentinel' so we don't hammer
    the rate-limit on every re-run — delete the file to force retry.
    On fresh fetch failure, write the sentinel and return 'failed'."""
    if path.exists():
        content = path.read_bytes()
        if _is_failed_sentinel(content):
            return 'sentinel'
        if not _is_incapsula_bounce(content):
            return 'cached'
    print(f'Fetching {label}...')
    try:
        content = _fetch_with_retry(url, referer=referer)
    except RuntimeError as e:
        print(f'  ! giving up on {label}: {e}', file=sys.stderr)
        path.write_bytes(FAILED_SENTINEL)
        return 'failed'
    path.write_bytes(content)
    time.sleep(post_delay)
    return 'fetched'


def fetch_surrey_council() -> dict[str, int]:
    """Fetch each unitary's mycouncil index, then every per-ward page it
    links to. Idempotent. Returns a {status: count} dict."""
    tallies: dict[str, int] = {}

    def tally(status: str) -> None:
        tallies[status] = tallies.get(status, 0) + 1

    for code, _name, _title, _districts in SURREY_UNITARIES:
        url = SURREY_COUNCIL_INDEX_URLS[code]
        eid = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['EID'][0]
        idx_path = SOURCE / f'surrey_council_index_{eid}.html'
        idx_status = _cached_or_fetch(
            idx_path, url, label=f'mycouncil index {code} (EID={eid})'
        )
        tally(f'index_{idx_status}')
        if idx_status == 'failed':
            continue  # can't walk a missing index

        index_html = idx_path.read_text('utf-8', errors='replace')
        base = url.rsplit('/', 1)[0] + '/'
        seen_area_ids: set[str] = set()
        for m in DIV_LINK_RE.finditer(index_html):
            href = m.group(1)
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            area_id = qs.get('ID', [None])[0]
            if not area_id or area_id in seen_area_ids:
                continue
            seen_area_ids.add(area_id)
            ward_path = SOURCE / f'surrey_council_ward_{area_id}.html'
            ward_url = urllib.parse.urljoin(base, href)
            tally(f'ward_{_cached_or_fetch(ward_path, ward_url, label=f"mycouncil ward {area_id} ({code})", referer=url)}')
    return tallies


def fetch_electionmap() -> dict[str, int]:
    tallies: dict[str, int] = {}
    for code, _name, _title, _districts in SURREY_UNITARIES:
        url = SURREY_ELECTIONMAP_URLS[code]
        path = SOURCE / f'surrey_electionmap_{code}.html'
        status = _cached_or_fetch(path, url, label=f'electionmap {code}')
        tallies[status] = tallies.get(status, 0) + 1
    return tallies


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)

    wiki_fetched, wiki_skipped, misses = fetch_wikipedia()
    council_tally = fetch_surrey_council()
    em_tally = fetch_electionmap()

    print(
        f'\nWikipedia: fetched {wiki_fetched}, skipped {wiki_skipped} '
        f'(already cached), {len(misses)} miss(es).'
    )
    print(
        f'Surrey CC: '
        f"index {council_tally.get('index_fetched', 0)} fetched / "
        f"{council_tally.get('index_cached', 0)} cached / "
        f"{council_tally.get('index_sentinel', 0)} skipped (sentinel) / "
        f"{council_tally.get('index_failed', 0)} failed · "
        f"ward {council_tally.get('ward_fetched', 0)} fetched / "
        f"{council_tally.get('ward_cached', 0)} cached / "
        f"{council_tally.get('ward_sentinel', 0)} skipped (sentinel) / "
        f"{council_tally.get('ward_failed', 0)} failed (Incapsula blocked)."
    )
    print(
        f"Electionmap: {em_tally.get('fetched', 0)} fetched, "
        f"{em_tally.get('cached', 0)} cached, "
        f"{em_tally.get('failed', 0)} failed."
    )
    if council_tally.get('ward_failed', 0):
        print(
            '  Note: failed mycouncil wards will fall back to Wikipedia in 23.\n'
            '  Re-run 22 later to retry — Incapsula rate-limits ease after '
            'idle time.', file=sys.stderr,
        )
    if misses:
        print("\nMisses — confirm the Wikipedia article title for these:")
        for t in misses:
            print(f'  "{t}"')


if __name__ == '__main__':
    main()
