"""Parse Oldham Council's bespoke single-page election results article.

Oldham publishes every ward's results on one results page (20 wards in
20 <h2>WardName</h2> blocks, surrounded by a couple of non-ward h2s
for site navigation that simply lack a results table). Each ward block
holds a <table> of candidates as <tr><td>NAME</td><td>PARTY</td>
<td>VOTES</td></tr> rows; the elected candidate's row carries
<strong>VOTES Elected</strong> in the votes cell only.

`official_url` is the article page; default urllib GET works (no
Cloudflare). The cached file is the raw HTML.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party

extension = 'html'

WARD_HEAD_RE = re.compile(r'<h2[^>]*>\s*([^<]+?)\s*</h2>', re.IGNORECASE)

ELECTED_ROW_RE = re.compile(
    r'<tr[^>]*>\s*'
    r'<td[^>]*>\s*([^<]+?)\s*</td>\s*'
    r'<td[^>]*>\s*([^<]+?)\s*</td>\s*'
    r'<td[^>]*>\s*<strong[^>]*>\s*([\d,]+)\s+Elected\s*</strong>\s*</td>',
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
        em = ELECTED_ROW_RE.search(src, block_start, block_end)
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
