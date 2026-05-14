"""Parse Trafford Council's bespoke single-page election results article.

Trafford publishes every ward on one results page (21 wards in 21
<h2 id="ward-slug">WardName</h2> blocks, plus a handful of non-ward
h2s for site nav/footer that lack a results table). Each block holds
a 4-column table — Surname | Forename(s) | Description | Votes — and
the elected candidate's row wraps every cell in <strong>...</strong>
with an asterisk after the vote count (e.g. <strong>1744*</strong>).

`official_url` is the article page; default urllib GET works (no
Cloudflare). The cached file is the raw HTML.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party

extension = 'html'

WARD_HEAD_RE = re.compile(r'<h2[^>]*>\s*([^<]+?)\s*</h2>', re.IGNORECASE)

# Each cell of the elected row opens with a <strong>; some cells split
# their text across two <strong> tags joined by <br> (e.g. Ashton Upon
# Mersey's "Labour and Co"<br>"operative Party"). Capture the full cell
# contents between <td...> and </td>, requiring a leading <strong>
# (losing rows are bare text and won't match), and clean up tags
# afterwards. The non-greedy .+? stops at the first </td>.
TAG_RE = re.compile(r'<[^>]+>')
ELECTED_ROW_RE = re.compile(
    r'<tr[^>]*>\s*'
    r'<td[^>]*>\s*(<strong[^>]*>.+?)</td>\s*'
    r'<td[^>]*>\s*(<strong[^>]*>.+?)</td>\s*'
    r'<td[^>]*>\s*(<strong[^>]*>.+?)</td>\s*'
    r'<td[^>]*>\s*(<strong[^>]*>.+?)</td>',
    re.DOTALL | re.IGNORECASE,
)


def _cell_text(raw: str) -> str:
    """Strip inner tags and collapse whitespace for a captured <td> cell."""
    return ' '.join(html.unescape(TAG_RE.sub(' ', raw)).split())


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
        surname = _cell_text(em.group(1))
        forename = _cell_text(em.group(2))
        votes_text = _cell_text(em.group(4)).rstrip('*').strip()
        out.append({
            'lad_code':  council['lad_code'],
            'council':   council['name'],
            'ward':      ward_name,
            'party':     normalize_party(_cell_text(em.group(3))),
            'candidate': f'{forename} {surname}',
            'votes':     int(votes_text.replace(',', '')),
            'source':    source,
        })
    return out
