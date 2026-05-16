"""Parse Oxford City Council 2026 ward results from oxford.gov.uk.

Each ward block opens with `<caption>Table showing list of candidates
for WardName ward</caption>` inside its own `<table>`, followed by
candidate rows in a 4-column table (Name | Description | Votes | Elected?).
The elected candidate's row wraps every cell in `<strong>...</strong>`
and the 4th cell text is "Elected" (loser rows carry "-").

Candidate cells split surname/forename across `<br>` (e.g. ROWLEY<br />
Mike) — the per-row cell extractor handles both styles.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

CAPTION_RE = re.compile(
    r'<caption>\s*Table showing list of candidates for\s*([^<]+?)\s*</caption>',
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
    captions = list(CAPTION_RE.finditer(src))
    for i, m in enumerate(captions):
        ward_name = html.unescape(m.group(1).strip())
        # Strip trailing " ward" suffix if present — keep the canonical name.
        ward_name = re.sub(r'\s+ward$', '', ward_name, flags=re.IGNORECASE)
        block_start = m.end()
        block_end = captions[i + 1].start() if i + 1 < len(captions) else len(src)
        elected: list[tuple[str, str, int]] = []
        for rm in ROW_RE.finditer(src, block_start, block_end):
            cells = [_cell_text(c.group(1)) for c in CELL_RE.finditer(rm.group(1))]
            if len(cells) < 4 or cells[3].lower() != 'elected':
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
