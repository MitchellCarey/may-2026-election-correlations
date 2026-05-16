"""Parse Pendle Borough Council 2026 ward results from pendle.gov.uk.

Each ward block opens with `<h3>WardName Ward</h3>` followed by a 3-column
table (Name of Candidate | Description | Number of Votes). The elected
candidate's row carries a literal " E" suffix on the votes cell (e.g.
"970 E"); losing rows are bare digits.

`official_url` is `/results`; default urllib GET works.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

WARD_HEAD_RE = re.compile(
    r'<h3[^>]*>\s*([^<]+?Ward)\s*</h3>',
    re.IGNORECASE,
)

ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
CELL_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r'<[^>]+>')

ELECTED_VOTES_RE = re.compile(r'^([\d,]+)\s+E\b', re.IGNORECASE)


def _cell_text(raw: str) -> str:
    return ' '.join(html.unescape(TAG_RE.sub(' ', raw)).split())


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    src = content.decode('utf-8', errors='replace')
    source = urllib.parse.urlparse(council['official_url']).netloc

    out: list[dict] = []
    ward_heads = list(WARD_HEAD_RE.finditer(src))
    for i, m in enumerate(ward_heads):
        ward_name = html.unescape(m.group(1).strip())
        # H3 heads carry a literal " Ward" suffix; strip it so the name
        # matches the WD24 polygon set used by 04c.
        ward_name = re.sub(r'\s+Ward$', '', ward_name, flags=re.IGNORECASE)
        block_start = m.end()
        block_end = ward_heads[i + 1].start() if i + 1 < len(ward_heads) else len(src)
        elected: list[tuple[str, str, int]] = []
        for rm in ROW_RE.finditer(src, block_start, block_end):
            cells = [_cell_text(c.group(1)) for c in CELL_RE.finditer(rm.group(1))]
            if len(cells) < 3:
                continue
            vm = ELECTED_VOTES_RE.match(cells[2])
            if not vm:
                continue
            try:
                votes = int(vm.group(1).replace(',', ''))
            except ValueError:
                continue
            elected.append((cells[1], cells[0], votes))
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
