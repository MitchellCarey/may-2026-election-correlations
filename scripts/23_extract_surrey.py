"""Parse the cached 2026 Surrey unitary Wikipedia articles into one record
per ward.

Reads data/source/wiki_surrey_<slug>_2026.json (one file per unitary,
produced by 22) and writes data/surrey_2026.json:

    [
      {
        "lad_code":  "XSE",
        "lad_name":  "East Surrey",
        "ward_code": "XSE::cobham_oxshott_south",
        "ward_name": "Cobham & Oxshott South",
        "winner":    "Conservative",        // plurality among winners
        "seats_won": {"Conservative": 2},   // seats per party (sums to 2)
        "year":      2026,
        "votes":     {"Conservative": 5324, "LibDem": 2963, ...},
        "source":    "wiki:2026 East Surrey Council election"
      },
      ...
    ]

Parser notes:

Every ward is wrapped in a `{{Election box begin no change|title=NAME...}}`
... `{{Election box end}}` block. Each block contains a mix of
`{{Election box winning candidate with party link no change | ...}}` (one
per elected seat — East Surrey has 36 wards × 2 seats = 72; West Surrey
has 45 × 2 = 90) and `{{Election box candidate with party link no change | ...}}`
(losing candidates). The party / votes / candidate fields share the same
schema across both template variants, so we parse them uniformly and use
the "winning" marker on the template name to set seat allocation.

The ward name comes from `title=NAME (2 seats)` — strip the trailing
"(N seats)" marker if present (East Surrey uses it; West Surrey omits it).
"""
import json
import re
import sys
from pathlib import Path

from _surrey_unitaries import SURREY_UNITARIES
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "surrey_2026.json"

BOX_BEGIN_RE = re.compile(
    r'\{\{\s*Election box begin(?:\s+no change)?\s*\|\s*title\s*=\s*([^|}\n]+?)\s*(?:\||\}\})',
    re.IGNORECASE,
)
BOX_END_RE = re.compile(r'\{\{\s*Election box end\s*\}\}', re.IGNORECASE)

# Match both winner and loser candidate templates. Group 1 captures
# "winning " when the candidate was elected, "" otherwise. Body capture
# (group 2) tolerates one level of brace nesting (e.g. <ref>{{cite ...}}</ref>).
CANDIDATE_TEMPLATE_RE = re.compile(
    r'\{\{\s*Election box (winning\s+)?candidate(?:\s+with party link)?(?:\s+no change)?'
    r'((?:[^{}]|\{\{[^{}]*\}\})*?)'
    r'\}\}',
    re.IGNORECASE | re.DOTALL,
)
PARTY_FIELD_RE = re.compile(r'\|\s*party\s*=\s*([^|\n]+)')
VOTES_FIELD_RE = re.compile(r'\|\s*votes\s*=\s*([\d,]+)')
CANDIDATE_FIELD_RE = re.compile(r'\|\s*candidate\s*=\s*([^|\n]+)')

SEATS_SUFFIX_RE = re.compile(r'\s*\(\d+\s*seats?\)\s*$', re.IGNORECASE)


def _slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def _clean_ward_name(raw: str) -> str:
    return SEATS_SUFFIX_RE.sub('', raw.strip())


def _parse_block(block: str) -> tuple[dict[str, int], dict[str, int], list[dict]]:
    """Return (seats_won, votes_per_party, winners_list) for one ward block."""
    seats: dict[str, int] = {}
    votes: dict[str, int] = {}
    winners: list[dict] = []
    for m in CANDIDATE_TEMPLATE_RE.finditer(block):
        is_winner = bool(m.group(1))
        body = m.group(2)
        pm = PARTY_FIELD_RE.search(body)
        vm = VOTES_FIELD_RE.search(body)
        cm = CANDIDATE_FIELD_RE.search(body)
        if not pm:
            continue
        party = normalize_party(pm.group(1))
        v = int(vm.group(1).replace(',', '')) if vm else 0
        votes[party] = votes.get(party, 0) + v
        if is_winner:
            seats[party] = seats.get(party, 0) + 1
            winners.append({
                'party': party,
                'candidate': cm.group(1).strip() if cm else None,
                'votes': v,
            })
    return seats, votes, winners


def _plurality_winner(seats: dict[str, int], votes: dict[str, int]) -> str:
    """Winner is the party with most seats; tie-break by total votes."""
    if not seats:
        return 'Pending'
    # Sort by seats DESC, then by votes DESC
    return max(seats.items(), key=lambda kv: (kv[1], votes.get(kv[0], 0)))[0]


def parse_unitary(wt: str, lad_code: str, lad_name: str,
                  wiki_title: str) -> list[dict]:
    rows: list[dict] = []
    # Walk Election box begin → Election box end pairs.
    pos = 0
    while True:
        bm = BOX_BEGIN_RE.search(wt, pos)
        if not bm:
            break
        em = BOX_END_RE.search(wt, bm.end())
        if not em:
            print(f'  ! {lad_code} {bm.group(1)!r}: no matching Election box end',
                  file=sys.stderr)
            break
        ward_raw = bm.group(1)
        ward_name = _clean_ward_name(ward_raw)
        block = wt[bm.end():em.start()]
        seats, votes, winners = _parse_block(block)
        rows.append({
            'lad_code':  lad_code,
            'lad_name':  lad_name,
            'ward_code': f'{lad_code}::{_slug(ward_name)}',
            'ward_name': ward_name,
            'winner':    _plurality_winner(seats, votes),
            'seats_won': seats,
            'winners':   winners,
            'year':      2026,
            'votes':     votes,
            'source':    f'wiki:{wiki_title}',
        })
        pos = em.end()
    return rows


def main():
    all_rows: list[dict] = []
    summary: list[str] = []
    pending: list[str] = []
    for code, name, wiki_title, _districts in SURREY_UNITARIES:
        slug = re.sub(r'[^a-z0-9]+', '_', wiki_title.lower()).strip('_')
        path = SOURCE / f'wiki_surrey_{slug}_2026.json'
        if not path.exists():
            print(f'  ! {code} {name}: missing cache {path.name}', file=sys.stderr)
            continue
        wt = json.loads(path.read_text())['parse']['wikitext']
        rows = parse_unitary(wt, code, name, wiki_title)
        decided = [r for r in rows if r['seats_won']]
        expected_seats = len(rows) * 2  # both unitaries are 2-member wards
        total_seats = sum(sum(r['seats_won'].values()) for r in rows)
        summary.append(
            f'{code} {name:<12} {len(rows):>2} wards · {len(decided):>2} decided · '
            f'{total_seats:>3}/{expected_seats} seats filled in by Wikipedia'
        )
        for r in rows:
            if not r['seats_won']:
                pending.append(f'{code}::{r["ward_name"]}')
        all_rows.extend(rows)

    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2))

    print('\n'.join(summary))
    if pending:
        print(
            f'\n  WARN {len(pending)} ward(s) have no winner marked in Wikipedia yet '
            '(article still being updated post-election):',
            file=sys.stderr,
        )
        for p in pending:
            print(f'    - {p}', file=sys.stderr)
        print(
            '  These wards will render as Pending (grey) until Wikipedia is updated; '
            're-run 22 → 23 to refresh.',
            file=sys.stderr,
        )

    n_xse = sum(1 for r in all_rows if r['lad_code'] == 'XSE')
    n_xsw = sum(1 for r in all_rows if r['lad_code'] == 'XSW')
    print(
        f'\nSaved {OUT.relative_to(ROOT)} — '
        f'{len(all_rows)} wards ({n_xse} XSE + {n_xsw} XSW)'
    )


if __name__ == '__main__':
    main()
