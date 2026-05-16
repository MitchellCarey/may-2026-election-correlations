"""Parse Bolton Council's bespoke single-page election results article.

Bolton publishes every ward's results on one news article page
(www.bolton.gov.uk/news/article/2037/local-election-results-2026 for
May 2026). Each ward is introduced by <h4>WardName</h4> and followed
by a <table> of candidates; the elected candidate's row is the one
whose votes cell contains "(elected)". Cell contents are wrapped in
<p>; the elected row also carries <strong>…</strong> wrappers.

`official_url` in the registry is the article page; the default urllib
GET works (no Cloudflare). The cached file is the raw HTML.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

WARD_HEAD_RE = re.compile(r'<h4[^>]*>\s*([^<]+?)\s*</h4>', re.IGNORECASE)

ELECTED_ROW_RE = re.compile(
    r'<tr[^>]*>\s*'
    r'<td[^>]*>\s*<p[^>]*>(?:<strong[^>]*>)?\s*([^<]+?)\s*(?:</strong>)?\s*</p>\s*</td>\s*'
    r'<td[^>]*>\s*<p[^>]*>(?:<strong[^>]*>)?\s*([^<]+?)\s*(?:</strong>)?\s*</p>\s*</td>\s*'
    r'<td[^>]*>\s*<p[^>]*>(?:<strong[^>]*>)?\s*([\d,]+)\s*\(elected\)\s*(?:</strong>)?\s*</p>\s*</td>',
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
        elected = [
            (
                html.unescape(em.group(2).strip()),
                html.unescape(em.group(1).strip()),
                int(em.group(3).replace(',', '')),
            )
            for em in ELECTED_ROW_RE.finditer(src, block_start, block_end)
        ]
        winner = pick_plurality(elected)
        if winner is None:
            continue
        party_raw, candidate, votes = winner
        out.append({
            'lad_code':  council['lad_code'],
            'council':   council['name'],
            'ward':      ward_name,
            'party':     normalize_party(party_raw),
            'candidate': candidate,
            'votes':     votes,
            'source':    source,
        })
    return out
