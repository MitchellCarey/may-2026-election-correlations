"""Parse Norwich City Council 2026 ward results from norwich.gov.uk.

Each ward block lives inside a LocalGov accordion pane. The ward name is
in `<span class="accordion-pane__heading">WardName Ward - results in</span>`
inside the pane title `<h3>`. Inside the pane content sits a 4-column
table (Candidate Name | Political party | Votes | Elected); the elected
row carries an "x" sentinel in the 4th `<td>` (losing rows hold `&nbsp;`).

Candidate cells split surname/forename across `<strong>...</strong>`
markup (e.g. `<td><strong>Smith</strong> Amber</td>`).
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

WARD_HEAD_RE = re.compile(
    r'<span[^>]*class="accordion-pane__heading"[^>]*>\s*'
    r'([^<]+?)\s*-\s*results in\s*</span>',
    re.IGNORECASE,
)

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
            if len(cells) < 4 or cells[3].lower() != 'x':
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
