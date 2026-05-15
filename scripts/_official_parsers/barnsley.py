"""Parse Barnsley Metropolitan Borough Council 2026 ward results from
barnsley.gov.uk.

Barnsley ran all-up in 2026 (post-review). Each ward block opens with
`<h3>WardName ward</h3>` and contains a 3-column table (Name | Party |
Votes) inside `<p>` wrappers per cell. The elected candidate's row wraps
every cell in `<strong>...</strong>` and the votes cell text takes the
form "N - ELECTED" (e.g. "1,181 - ELECTED").
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

WARD_HEAD_RE = re.compile(r'<h3[^>]*>\s*([^<]+?)\s*</h3>', re.IGNORECASE)

ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
CELL_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r'<[^>]+>')

ELECTED_VOTES_RE = re.compile(r'^([\d,]+)\s*-\s*ELECTED\s*$', re.IGNORECASE)


def _cell_text(raw: str) -> str:
    return ' '.join(html.unescape(TAG_RE.sub(' ', raw)).split())


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    src = content.decode('utf-8', errors='replace')
    source = urllib.parse.urlparse(council['official_url']).netloc

    out: list[dict] = []
    ward_heads = list(WARD_HEAD_RE.finditer(src))
    for i, m in enumerate(ward_heads):
        # Re-strip post-unescape so a trailing `&nbsp;` (Central) collapses.
        ward_name = html.unescape(m.group(1).strip()).strip()
        block_start = m.end()
        block_end = ward_heads[i + 1].start() if i + 1 < len(ward_heads) else len(src)
        # The page tail repeats the same h3+table layout for Parish/Town
        # Council seats — skip those since they aren't WD24 wards.
        if 'Council' in ward_name or not ward_name.lower().endswith(' ward'):
            continue
        # H3 heads carry a literal " ward" suffix ("Central ward"); strip
        # it so the name matches the WD24 polygon set used by 04c.
        ward_name = re.sub(r'\s+ward$', '', ward_name, flags=re.IGNORECASE)
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
