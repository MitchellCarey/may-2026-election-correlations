"""Parse Dudley Metropolitan Borough Council's bespoke results page.

Dudley publishes every ward's results on one HTML page
(online.dudley.gov.uk/elections/local2026-live.asp). Each ward is a
self-contained <table summary="WardName Ward Results"> with three
columns per row — a marker cell (the elected row carries
"Elected<br>(HH:MM)", losing rows carry "&nbsp;", and a final
"Spoilt Papers" row also carries "&nbsp;"), a "Surname[ [Surname]],
Forename[ [Forename]]<br>Party" candidate cell, and a "votes (pct%)"
cell.

The 2026 contest is normally one seat per ward (thirds cycle), but
Wollaston & Stourbridge Town had two seats up due to a casual vacancy,
yielding two `Elected` rows in that block; `pick_plurality` collapses
them to one row per ward.

The summary attribute carries the ward name suffixed " Ward" — strip
the suffix so the WD24 normalised join matches (WD24 names omit it).

`official_url` is the live page; the default urllib GET works.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pick_winner import pick_plurality

extension = 'html'

WARD_HEAD_RE = re.compile(
    r'<table[^>]*\bsummary="([^"]+?)\s+Ward\s+Results"',
    re.IGNORECASE,
)

ELECTED_ROW_RE = re.compile(
    r'<tr[^>]*>\s*'
    r'<td[^>]*>\s*Elected\b[^<]*(?:<br\s*/?>[^<]*)?\s*</td>\s*'
    r'<td[^>]*>\s*([^<]+?)\s*<br\s*/?>\s*([^<]+?)\s*</td>\s*'
    r'<td[^>]*>\s*([\d,]+)\b',
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
        elected = [
            (
                html.unescape(em.group(2).strip()),
                html.unescape(em.group(1).strip()),
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
