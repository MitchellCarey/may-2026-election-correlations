"""Cloudflare-bypass HTTP helpers for official-source parsers.

Some council results pages sit behind Cloudflare's bot challenge — a
JavaScript-tagged 403 returned to anything whose TLS handshake doesn't
match a real browser. urllib's vanilla fingerprint is rejected; this
helper issues requests via curl_cffi, which ships pre-built libcurl
variants that mimic real-browser TLS / HTTP-2 fingerprints (chrome,
safari, firefox, edge). With `impersonate='chrome120'` we get past the
"Just a moment..." page with a clearance cookie, which the Session
caches and reuses across subsequent GETs.

Usage from a parser module:

    from _cloudflare import cloudflare_session

    def fetch(url, *, council, year):
        with cloudflare_session() as s:
            index_html = s.get(url).content
            ...

The module is private (leading underscore is documentation only; the
dispatcher in 12_fetch_official_results.py would happily import it if
a council declared `official_parser: _cloudflare`, but none does).

`curl_cffi` is imported lazily inside the helpers so contributors who
run unrelated scripts (10/14/19/20 etc.) don't need the wheel installed.
"""
from contextlib import contextmanager


UA_SUFFIX = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'


@contextmanager
def cloudflare_session(*, impersonate: str = 'chrome120', timeout: float = 30.0):
    """Yield a curl_cffi.requests.Session impersonating a real browser.

    Reusing one Session across N requests amortises the Cloudflare
    challenge: the cf_clearance cookie set on the first 200 is sent on
    every subsequent GET, so we pay the challenge cost once per
    parser run rather than once per division.
    """
    try:
        from curl_cffi import requests as _cffi
    except ImportError as e:
        raise RuntimeError(
            'curl_cffi is required for Cloudflare-bypass parsers but is not '
            'installed. Run `pip install -r requirements.txt`.'
        ) from e

    session = _cffi.Session(impersonate=impersonate, timeout=timeout)
    session.headers['User-Agent'] = (
        session.headers.get('User-Agent', '') + ' ' + UA_SUFFIX
    ).strip()
    try:
        yield session
    finally:
        session.close()


def fetch_cloudflare(url: str, *, impersonate: str = 'chrome120', timeout: float = 30.0) -> bytes:
    """One-shot GET via a Cloudflare-impersonating session.

    For parsers that only need a single page; multi-page parsers should
    use cloudflare_session() directly so the clearance cookie persists.
    """
    with cloudflare_session(impersonate=impersonate, timeout=timeout) as s:
        try:
            response = s.get(url)
        except Exception as e:
            raise RuntimeError(f'Cloudflare bypass failed for {url}: {e!r}') from e
        if response.status_code != 200:
            raise RuntimeError(
                f'Cloudflare bypass returned HTTP {response.status_code} for {url}'
            )
        return response.content
