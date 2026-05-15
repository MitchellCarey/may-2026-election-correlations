"""Parse Walsall Council 2026 ward results from go.walsall.gov.uk.

Walsall publishes a single-page "election timeline" listing every ward
inline (not the per-ward subpages the survey first suggested). Each
ward block opens with

    <h3 class="election-timeline__area-name">
      <a class="election-timeline__area-link" href="...">WardName</a>
    </h3>

and the candidates follow as a list of `<div class="election-timeline__
candidate ...">` blocks. Elected candidates carry the extra modifier
class `election-timeline__candidate--winner` on the same div; each
candidate's party / name / votes are in three `<span>` siblings.

Walsall ran all-up in 2026 (post-review); `pick_plurality` collapses
each multi-seat ward to a single CSV row.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

WARD_HEAD_RE = re.compile(
    r'<h3[^>]*class="election-timeline__area-name"[^>]*>\s*'
    r'<a[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)

WINNER_BLOCK_RE = re.compile(
    r'<div[^>]*class="[^"]*election-timeline__candidate--winner[^"]*"[^>]*>'
    r'(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)

PARTY_RE = re.compile(
    r'<span[^>]*class="election-timeline__candidate-party"[^>]*>\s*([^<]+?)\s*</span>',
    re.IGNORECASE,
)
NAME_RE = re.compile(
    r'<span[^>]*class="election-timeline__candidate-name"[^>]*>\s*([^<]+?)\s*</span>',
    re.IGNORECASE,
)
VOTES_RE = re.compile(
    r'<span[^>]*class="election-timeline__candidate-votes"[^>]*>\s*([\d,]+)',
    re.IGNORECASE,
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
        elected: list[tuple[str, str, int]] = []
        for wm in WINNER_BLOCK_RE.finditer(src, block_start, block_end):
            inner = wm.group(1)
            pm = PARTY_RE.search(inner)
            nm = NAME_RE.search(inner)
            vm = VOTES_RE.search(inner)
            if not (pm and nm and vm):
                continue
            try:
                votes = int(vm.group(1).replace(',', ''))
            except ValueError:
                continue
            elected.append((
                html.unescape(pm.group(1).strip()),
                html.unescape(nm.group(1).strip()),
                votes,
            ))
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
