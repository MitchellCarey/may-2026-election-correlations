"""Parse moderngov-style per-division results from a host with bot-blocker
TLS challenge (Cloudflare, Incapsula, Akamai, etc.).

Identical parsing logic to `moderngov_per_division`, but fetch() routes
through `_cloudflare.cloudflare_session()` (curl_cffi Chrome impersonation)
so the index + per-division GETs all carry a real-browser TLS fingerprint
and reuse the bot-challenge clearance cookie across requests.

Used by Surrey 2021 (`mycouncil.surreycc.gov.uk` is fronted by Incapsula).
The `parse()` step is delegated to moderngov_per_division so the regex
stays single-sourced — any improvement to the elected-row pattern there
benefits both parsers.
"""
import html
import json
import time
import urllib.parse

from ._cloudflare import cloudflare_session
from .moderngov_per_division import DIV_LINK_RE, parse as _parse

extension = 'json'


def fetch(url: str, *, council: dict, year: int) -> bytes:
    """Fetch the index + every per-division page via a curl_cffi session.

    The single session reuses the bot-challenge clearance cookie across
    GETs, so we pay the challenge cost once per parser run.
    """
    parsed = urllib.parse.urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}{parsed.path.rsplit("/", 1)[0]}/'
    divisions: dict[str, str] = {}
    with cloudflare_session() as s:
        index_html = s.get(url).content.decode('utf-8', errors='replace')
        for m in DIV_LINK_RE.finditer(index_html):
            href = m.group(1)
            name = html.unescape(m.group(2))
            div_url = urllib.parse.urljoin(base, href)
            time.sleep(0.3)
            divisions[name] = s.get(div_url).content.decode(
                'utf-8', errors='replace')
    return json.dumps({
        'index_url': url,
        'divisions': divisions,
    }).encode()


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    return _parse(content, council=council, year=year)
