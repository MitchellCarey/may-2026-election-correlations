"""Parse Manchester City Council's election results directory page.

Manchester publishes every ward's results on one online-directories
page (32 wards in 32 <h3>WardName</h3> blocks). Each block holds a
<ul> of candidates as plain <li> rows in the form

    NAME, Firstname (Party Name): N votes

with the elected candidate's <li> wrapped in <strong>…</strong> and
suffixed " - elected" inside the strong wrapper.

`official_url` is the article page; default urllib GET works (the
council's CDN is a passive Cloudflare cache that does not challenge a
stock UA). The cached file is the raw HTML.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party

extension = 'html'

WARD_HEAD_RE = re.compile(r'<h3[^>]*>\s*([^<]+?)\s*</h3>', re.IGNORECASE)

ELECTED_LI_RE = re.compile(
    r'<li[^>]*>\s*<strong[^>]*>\s*'
    r'([^<]+?)\s*\(\s*([^)]+?)\s*\)\s*:\s*([\d,]+)\s+votes?\s*-\s*elected\s*'
    r'</strong>\s*</li>',
    re.DOTALL | re.IGNORECASE,
)


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    src = content.decode('utf-8', errors='replace')
    source = urllib.parse.urlparse(council['official_url']).netloc

    out: list[dict] = []
    ward_heads = list(WARD_HEAD_RE.finditer(src))
    for i, m in enumerate(ward_heads):
        ward_name = html.unescape(m.group(1).strip())
        block_start = m.end()
        block_end = ward_heads[i + 1].start() if i + 1 < len(ward_heads) else len(src)
        em = ELECTED_LI_RE.search(src, block_start, block_end)
        if not em:
            continue
        out.append({
            'lad_code':  council['lad_code'],
            'council':   council['name'],
            'ward':      ward_name,
            'party':     normalize_party(html.unescape(em.group(2).strip())),
            'candidate': html.unescape(em.group(1).strip()),
            'votes':     int(em.group(3).replace(',', '')),
            'source':    source,
        })
    return out
