"""Parse the cached 2026 Senedd Wikipedia articles into one record per
constituency.

Reads data/source/wiki_senedd_<slug>_2026.json (one file per constituency,
produced by 14) and writes data/senedd_2026.json:

    [
      {
        "code":     "S02",
        "name":     "Bangor Conwy Môn",
        "plurality_party": "Plaid",
        "year":     2026,
        "seats":    {"Plaid": 3, "Reform": 2, "Conservative": 1},
        "votes":    {"Plaid": 31057, "Reform": 19440, ...}
      },
      ...
    ]

Parser notes:

Vote totals come from the {{Election box candidate with party link}}
templates inside the {{Election box begin|title=[[2026 Senedd election]]:…}}
block — every article uses this template family and exposes a `votes=N`
field on each party row.

Seat allocation comes from the "Members of the Senedd" table at the top
of every article. That table renders the 6 elected MSs as a single
horizontal row with one `bgcolor="{{party color|PARTY}}"` cell per seat,
so counting `{{party color|…}}` occurrences inside the section gives the
6-way seat split directly. We prefer this over parsing the elected-marker
convention (`(E)` / `(elected N)`) inside the Election box because the
two conventions diverge across the 16 articles (e.g. Brycheiniog Tawe Nedd
omits markers entirely) while the Members table is uniform.
"""
import json
import re
import sys
from pathlib import Path

from _senedd_constituencies import SENEDD_CONSTITUENCIES
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "senedd_2026.json"

# Open the 2026 Senedd results block. The article body may also contain a
# "2021 notional result" table — anchoring on this specific title prevents
# that block from leaking into the parse.
RESULTS_BEGIN_RE = re.compile(
    r'\{\{\s*Election box begin\s*\|\s*title\s*=\s*\[\[2026 Senedd election\]\]:',
    re.IGNORECASE,
)
RESULTS_END_RE = re.compile(r'\{\{\s*Election box end\s*\}\}', re.IGNORECASE)

# One {{Election box candidate with party link|…}} template per party. The
# body can span multiple lines and embed nested templates (e.g. {{cite news}}
# inside <ref>); allow one level of brace nesting via the alternation.
PARTY_TEMPLATE_RE = re.compile(
    r'\{\{\s*Election box candidate(?:\s+with party link)?'
    r'((?:[^{}]|\{\{[^{}]*\}\})*?)'
    r'\}\}',
    re.IGNORECASE | re.DOTALL,
)

PARTY_FIELD_RE = re.compile(r'\|\s*party\s*=\s*([^|\n]+)')
VOTES_FIELD_RE = re.compile(r'\|\s*votes\s*=\s*([\d,]+)')

# The Members-of-the-Senedd table sits in different places across articles
# (some have it under an H2 heading "Members of the Senedd", Casnewydd
# Islwyn places it inline with no heading at all), so anchor on the
# `[[2026 Senedd election|2026]]` row link rather than a heading. In
# MediaWiki table syntax a row is bounded by `|-` (next-row separator)
# OR `|}` (table close); today the 2026 row is the last row in every
# article so the row terminator is `|}`, not `|-`. The trailing lookahead
# must accept either, otherwise the capture spills past the table close
# into the Election box below it and any future {{party color|…}}
# template added downstream would inflate the seat count.
SEAT_ROW_RE = re.compile(
    r'\|-(?P<row>(?:(?!\|-).)*?\[\[2026 Senedd election\|2026\]\].*?)(?=\|-|\|\})',
    re.IGNORECASE | re.DOTALL,
)
SEAT_COLOR_RE = re.compile(r'\{\{\s*party color\s*\|\s*([^|}\n]+?)\s*\}\}',
                           re.IGNORECASE)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _extract_votes(wt: str) -> dict[str, int]:
    """Parse per-party vote totals from the 2026 Senedd Election box."""
    begin = RESULTS_BEGIN_RE.search(wt)
    if not begin:
        raise ValueError("no '2026 Senedd election' Election box found")
    end = RESULTS_END_RE.search(wt, begin.end())
    if not end:
        raise ValueError("Election box begin without matching end")
    block = wt[begin.end():end.start()]

    votes: dict[str, int] = {}
    for m in PARTY_TEMPLATE_RE.finditer(block):
        body = m.group(1)
        pm = PARTY_FIELD_RE.search(body)
        vm = VOTES_FIELD_RE.search(body)
        if not pm or not vm:
            continue
        party = normalize_party(pm.group(1))
        v = int(vm.group(1).replace(',', ''))
        votes[party] = votes.get(party, 0) + v
    if not votes:
        raise ValueError("no party-vote rows parsed inside Election box")
    return votes


def _extract_seats(wt: str) -> dict[str, int]:
    """Parse the 6-seat allocation from the Members-of-the-Senedd table."""
    rm = SEAT_ROW_RE.search(wt)
    if not rm:
        raise ValueError("no Members-of-the-Senedd row with 2026 anchor")
    row = rm.group('row')
    seats: dict[str, int] = {}
    for cm in SEAT_COLOR_RE.finditer(row):
        party = normalize_party(cm.group(1))
        seats[party] = seats.get(party, 0) + 1
    return seats


def parse_constituency(wt: str) -> tuple[str, dict, dict]:
    """Return (plurality_party, seats_dict, votes_dict) for one constituency."""
    votes = _extract_votes(wt)
    seats = _extract_seats(wt)
    plurality = max(sorted(votes), key=lambda p: votes[p])
    return plurality, seats, votes


def main():
    out_rows = []
    misses: list[str] = []
    for code, display_name, wiki_title in SENEDD_CONSTITUENCIES:
        path = SOURCE / f'wiki_senedd_{_slug(wiki_title)}_2026.json'
        if not path.exists():
            misses.append(f'{code} {display_name}: missing cache {path.name}')
            continue
        wt = json.loads(path.read_text())['parse']['wikitext']
        try:
            plurality, seats, votes = parse_constituency(wt)
        except ValueError as e:
            misses.append(f'{code} {display_name}: {e}')
            continue

        seat_total = sum(seats.values())
        if seat_total != 6:
            print(
                f'  WARN {code} {display_name}: parsed {seat_total} elected MSs '
                f'(expected 6) — seats: {seats}',
                file=sys.stderr,
            )
        seat_summary = ' / '.join(
            f'{p} {n}' for p, n in sorted(seats.items(), key=lambda kv: -kv[1])
        )
        print(f'{code} {display_name:35} plurality={plurality:>12}  seats: {seat_summary}')
        out_rows.append({
            'code':             code,
            'name':             display_name,
            'plurality_party':  plurality,
            'year':             2026,
            'seats':            seats,
            'votes':            votes,
        })

    if misses:
        print(file=sys.stderr)
        for m in misses:
            print(f'  ! {m}', file=sys.stderr)

    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out_rows, ensure_ascii=False, indent=2))

    total_seats = sum(sum(r['seats'].values()) for r in out_rows)
    print(
        f'\nSaved {OUT.relative_to(ROOT)} — '
        f'{len(out_rows)}/{len(SENEDD_CONSTITUENCIES)} constituencies, '
        f'{total_seats}/96 seats accounted for'
    )


if __name__ == '__main__':
    main()
