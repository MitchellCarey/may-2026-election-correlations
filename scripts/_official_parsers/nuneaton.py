"""Parse Nuneaton & Bedworth Borough Council 2026 ward results from
nuneatonandbedworth.gov.uk.

Each ward block opens with `<h3>WardName</h3>` followed by

    <p><strong>Party Gain from OtherParty</strong></p>
    <p><strong>Party Hold</strong></p>

then an `<ul>` of candidates as `<li>Forename Surname (Party): Votes</li>`.
There is no per-row "Elected" sentinel — the winning party is read from
the gain/hold paragraph; the winning candidate is the top-vote `<li>`
belonging to that party.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

WARD_HEAD_RE = re.compile(r'<h3[^>]*>\s*([^<]+?)\s*</h3>', re.IGNORECASE)

# Captures the winning party word(s) before "Gain" or "Hold" inside a
# <p><strong>...</strong></p> paragraph.
GAIN_HOLD_RE = re.compile(
    r'<p[^>]*>\s*<strong[^>]*>\s*([^<]+?)\s+(?:Gain|Hold)\b[^<]*</strong>\s*</p>',
    re.IGNORECASE,
)

# Each candidate is `<li>NAME (Party): N votes-or-just-N</li>`.
LI_RE = re.compile(
    r'<li[^>]*>\s*([^<(]+?)\s*\(\s*([^)]+?)\s*\)\s*:\s*([\d,]+)\s*</li>',
    re.DOTALL | re.IGNORECASE,
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

        gh = GAIN_HOLD_RE.search(src, block_start, block_end)
        if not gh:
            continue
        winning_party_raw = html.unescape(gh.group(1).strip())
        winning_party = normalize_party(winning_party_raw)

        # Collect all candidates; keep only those whose normalised party
        # matches the gain/hold party. The plurality picker then chooses
        # the top-vote one (works for both single- and multi-seat wards).
        slate: list[tuple[str, str, int]] = []
        for lm in LI_RE.finditer(src, block_start, block_end):
            candidate = html.unescape(lm.group(1).strip())
            party_raw = html.unescape(lm.group(2).strip())
            try:
                votes = int(lm.group(3).replace(',', ''))
            except ValueError:
                continue
            if normalize_party(party_raw) == winning_party:
                slate.append((party_raw, candidate, votes))
        winner = pick_plurality(slate)
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
