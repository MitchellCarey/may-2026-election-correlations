"""ModernGov per-division parser with Incapsula/Imperva fetch fallback.

Some councils run ModernGov behind Imperva (Incapsula) — most visibly
mycouncil.surreycc.gov.uk, but the same anti-bot tier shows up on a handful
of other instances surfaced by scripts/_phase4_survey_moderngov.py. The HTML
shape on the per-division pages is identical to a plain ModernGov host, so
we re-export parse() from moderngov_per_division and only override fetch():
plain urllib gets an Incapsula stub back; curl_cffi with a real-browser TLS
fingerprint gets the actual page.

JSON cache shape is identical to moderngov_per_division so
13_extract_official.py doesn't need to know which parser key produced the
file.

Used by: any council whose ModernGov host returns the Incapsula JS-challenge
bounce to plain urllib (set `official_parser: moderngov_per_division_incapsula`
in data/source/councils.yaml).
"""
import html
import json
import re
import time
import urllib.parse

from _cloudflare import cloudflare_session
# Re-export the HTML extraction logic — the per-division template is the
# same across plain and Incapsula-fronted ModernGov instances.
from moderngov_per_division import (  # noqa: F401
    DIV_LINK_RE,
    ELECTED_ROW_RE,
    extension,
    parse,
)

INCAPSULA_BOUNCE_RE = re.compile(
    rb'_Incapsula_Resource\?(SWUDNSAI|SWJIYLWA)|Request unsuccessful\. Incapsula incident'
)

# Same rotation 22_fetch_surrey_results.py uses — Incapsula scores TLS
# fingerprints over time, so cycling impersonations across retries defeats
# the adaptive block.
IMPERSONATIONS = ['chrome120', 'chrome116', 'chrome119', 'chrome124', 'edge101']


def _session_get(session, url: str, referer: str | None = None) -> bytes:
    headers = {'Referer': referer} if referer else {}
    response = session.get(url, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f'HTTP {response.status_code} for {url}')
    if INCAPSULA_BOUNCE_RE.search(response.content[:2000]):
        raise RuntimeError(f'Incapsula bounce for {url}')
    return response.content


def _fetch_with_retry(url: str, referer: str | None = None,
                      *, max_attempts: int = 3) -> bytes:
    """Open a fresh cloudflare_session per attempt with a rotating
    impersonation profile. Surrey CC's tier rate-limits bursts regardless of
    fingerprint, so we backoff between attempts; partial coverage is
    acceptable because 13 just records whatever the parser returns."""
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        impersonate = IMPERSONATIONS[(attempt - 1) % len(IMPERSONATIONS)]
        try:
            with cloudflare_session(impersonate=impersonate) as s:
                return _session_get(s, url, referer=referer)
        except RuntimeError as e:
            last_err = e
            if attempt < max_attempts:
                time.sleep(5.0 * attempt)
    raise RuntimeError(f'Gave up after {max_attempts} attempts: {last_err}')


def fetch(url: str, *, council: dict, year: int) -> bytes:
    """Fetch the index page via curl_cffi, then every per-division page it
    links to. Output schema matches moderngov_per_division.fetch()."""
    index_bytes = _fetch_with_retry(url)
    index_html = index_bytes.decode('utf-8', errors='replace')
    parsed = urllib.parse.urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}{parsed.path.rsplit("/", 1)[0]}/'
    divisions: dict[str, str] = {}
    for m in DIV_LINK_RE.finditer(index_html):
        href = m.group(1)
        name = html.unescape(m.group(2))
        div_url = urllib.parse.urljoin(base, href)
        time.sleep(0.5)  # be polite + amortise Incapsula rate limiter
        divisions[name] = _fetch_with_retry(div_url, referer=url).decode(
            'utf-8', errors='replace'
        )
    return json.dumps({
        'index_url': url,
        'divisions': divisions,
    }).encode()
