"""Parse the joint Adur + Worthing 2026 results portal.

Both councils publish their results on a single
adur-worthing.gov.uk page. The page lists every ward block as:

    <h3><a id="ward-slug"></a>WardName Ward</h3>
    <table><caption>WardName Ward</caption>... 3-col table ...</table>

The boundary between the two districts is signposted by an h3 that
contains "Adur District election results" (end of Adur, start of
Worthing). The parser receives `council['lad_code']` and emits rows
only for the matching district half.

Elected row: every cell wrapped in `<strong>`; the votes cell text ends
with " - elected" (e.g. `<strong>632 - elected</strong>`).
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

# Two boundaries on the page split it into three blocks:
#   [start ......... ADUR_BOUNDARY ......... WORTHING_BOUNDARY ......... end]
#   <-- Adur wards -->  <----- Worthing wards ----->  <-- WSCC etc. -->
ADUR_BOUNDARY_RE = re.compile(
    r'<h3[^>]*>(?:<[^>]+>)*[^<]*Adur District election results',
    re.IGNORECASE,
)
WORTHING_BOUNDARY_RE = re.compile(
    r'<h3[^>]*>(?:<[^>]+>)*[^<]*Worthing Borough election results',
    re.IGNORECASE,
)

CAPTION_RE = re.compile(
    r'<table[^>]*>\s*<caption>\s*([^<]+?)\s*</caption>',
    re.IGNORECASE,
)
ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
CELL_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r'<[^>]+>')

ELECTED_VOTES_RE = re.compile(r'^([\d,]+)\s*-\s*elected\s*$', re.IGNORECASE)


def _cell_text(raw: str) -> str:
    return ' '.join(html.unescape(TAG_RE.sub(' ', raw)).split())


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    src = content.decode('utf-8', errors='replace')
    source = urllib.parse.urlparse(council['official_url']).netloc

    am = ADUR_BOUNDARY_RE.search(src)
    adur_end = am.start() if am else len(src)
    wm = WORTHING_BOUNDARY_RE.search(src)
    worthing_end = wm.start() if wm else len(src)

    lad = council['lad_code']
    if lad == 'E07000223':  # Adur
        block_start, block_end = 0, adur_end
    elif lad == 'E07000229':  # Worthing
        block_start, block_end = adur_end, worthing_end
    else:
        return []

    out: list[dict] = []
    captions = [m for m in CAPTION_RE.finditer(src, block_start, block_end)]
    for i, m in enumerate(captions):
        ward_name = html.unescape(m.group(1).strip())
        # Strip trailing " Ward" suffix where it appears.
        ward_name = re.sub(r'\s+Ward$', '', ward_name, flags=re.IGNORECASE)
        cb_start = m.end()
        cb_end = captions[i + 1].start() if i + 1 < len(captions) else block_end
        elected: list[tuple[str, str, int]] = []
        for rm in ROW_RE.finditer(src, cb_start, cb_end):
            row = rm.group(1)
            # Only consider rows where every cell opens with <strong>.
            if row.count('<strong') < 3:
                continue
            cells = [_cell_text(c.group(1)) for c in CELL_RE.finditer(row)]
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
