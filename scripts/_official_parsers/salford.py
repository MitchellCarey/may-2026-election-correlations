"""Parse Salford City Council's bespoke single-page election results page.

Salford publishes every ward's results on one page (20 wards in 20
<h3>WardName</h3> blocks). Each block holds a <table> of candidates
in <tr><td>NAME</td><td>PARTY</td><td>VOTES</td></tr> rows. The
elected candidate's row wraps each cell's contents in <strong>...
</strong> (the candidate name lives inside <p><strong>NAME</strong>
</p> with stray <strong> </strong> wrappers around the <p>; party
and votes cells just hold a single <strong>X</strong>).

Cadishead and Lower Irlam carries a double vacancy — two elected rows,
both Reform UK today. To stay correct if a future double-vacancy ward
elects councillors from different parties, we collect every elected
row in a block and let _pick_winner.pick_plurality decide the row that
should land in the CSV.

`official_url` is the article page; default urllib GET works (no
Cloudflare). The cached file is the raw HTML.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

WARD_HEAD_RE = re.compile(r'<h3[^>]*>\s*([^<]+?)\s*</h3>', re.IGNORECASE)

# Elected row: candidate cell opens with a stray <strong> </strong>
# wrapper that only appears on elected rows (losing rows go straight
# to <p>NAME</p>); the <p> inside holds either a single <strong>NAME
# </strong> or two <strong> tags joined by <br> (Eccles splits its
# winner's name across two lines). Party and votes cells always wrap
# their text in <strong>. Anchoring on the leading-strong marker
# stops .+? from backtracking past losing rows to find the elected one.
ELECTED_ROW_RE = re.compile(
    r'<tr[^>]*>\s*'
    r'<td[^>]*>\s*<strong[^>]*>\s*</strong>\s*'
    r'<p[^>]*>(.+?)</p>'
    r'(?:\s*<strong[^>]*>\s*</strong>)?\s*</td>\s*'
    r'<td[^>]*>\s*<strong[^>]*>\s*([^<]+?)\s*</strong>\s*</td>\s*'
    r'<td[^>]*>\s*<strong[^>]*>\s*([\d,]+)\s*</strong>\s*</td>',
    re.DOTALL | re.IGNORECASE,
)

TAG_RE = re.compile(r'<[^>]+>')


def _candidate_text(raw: str) -> str:
    """Strip inner tags from the candidate <p> cell and collapse whitespace.
    Handles the single-<strong> case and the <strong>X</strong><br>
    <strong>Y</strong> case identically."""
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
        elected = [
            (
                html.unescape(em.group(2).strip()),
                _candidate_text(em.group(1)),
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
