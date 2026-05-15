"""Parse North East Lincolnshire Council 2026 ward results from
nelincs.gov.uk.

The `/your-council/elections-and-voting/election-dates-and-results/local-
elections/` page stacks past years' results below the current cycle.
Scope to the "Latest results" section by ending the scan at the
`<h2 id="local-election-results">Past local election results</h2>`
boundary.

Inside the Latest section each ward is a Kadence accordion pane:

    <span class="kt-blocks-accordion-title">WardName</span>
    …
    <table>… 3-col (Candidate | Party | No. of votes) …</table>
    <p>Candidates whose names are shown in bold type were elected.</p>

The elected row wraps every cell in `<strong>...</strong>`.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

LATEST_END_RE = re.compile(
    r'<h2[^>]*id="local-election-results"',
    re.IGNORECASE,
)
WARD_TITLE_RE = re.compile(
    r'<span[^>]*class="kt-blocks-accordion-title"[^>]*>\s*([^<]+?)\s*</span>',
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

    latest_end_m = LATEST_END_RE.search(src)
    latest_end = latest_end_m.start() if latest_end_m else len(src)

    out: list[dict] = []
    ward_titles = [m for m in WARD_TITLE_RE.finditer(src, 0, latest_end)]
    for i, m in enumerate(ward_titles):
        ward_name = html.unescape(m.group(1).strip())
        block_start = m.end()
        block_end = (
            ward_titles[i + 1].start() if i + 1 < len(ward_titles) else latest_end
        )
        elected: list[tuple[str, str, int]] = []
        for rm in ROW_RE.finditer(src, block_start, block_end):
            row = rm.group(1)
            # Elected row: every cell wraps its content in <strong>.
            if row.count('<strong') < 3:
                continue
            cells = [_cell_text(c.group(1)) for c in CELL_RE.finditer(row)]
            if len(cells) < 3:
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
