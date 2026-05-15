"""Parse Plymouth City Council 2026 ward results from plymouth.gov.uk.

Plymouth ran all-up in 2026 due to a 2024 boundary review, so multi-seat
wards return two or three elected councillors. Each ward block opens with
`<h3 id="{slug}">WardName</h3>` followed by a 4-column table — Candidate
| Party | Votes | Elected — where elected rows carry "Yes" in the 4th
`<td>` (losing rows are empty). Candidate cells split surname/forename
across a `<br>`; party cells may split a name across a `<br>` too (e.g.
"Conservative and<br>Unionist Party").

`official_url` is the canonical results page; default urllib GET works.
The cached file is the raw HTML.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

WARD_HEAD_RE = re.compile(
    r'<h3[^>]*\bid="[^"]+"[^>]*>\s*([^<]+?)\s*</h3>',
    re.IGNORECASE,
)

# Iterate full rows, then test each row for the elected sentinel.
# Anchoring on `<tr>...</tr>` boundaries avoids non-greedy `.+?` bleeding
# across rows when row N's 4th cell is empty (losing row) and the next row
# happens to satisfy a cross-row capture.
ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
CELL_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)

TAG_RE = re.compile(r'<[^>]+>')


def _cell_text(raw: str) -> str:
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
        elected: list[tuple[str, str, int]] = []
        for rm in ROW_RE.finditer(src, block_start, block_end):
            cells = [_cell_text(c.group(1)) for c in CELL_RE.finditer(rm.group(1))]
            if len(cells) < 4 or cells[3].lower() != 'yes':
                continue
            try:
                votes = int(cells[2].replace(',', ''))
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
