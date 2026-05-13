"""Parse the 2026 Scottish Parliament results wikitable into per-constituency
winners and emit data/holyrood_winners.json.

Pipeline position: 17 fetches the article, 18 parses + joins to SPC26 codes,
07d picks the JSON up as a new GB-only render layer.

Input:  data/source/wiki_holyrood_2026.json  (cached MediaWiki parse response)
        data/ward_geoms.json                 (for the SPC26CD ↔ name lookup)
        data/source/holyrood_name_overrides.csv  (optional; same shape as
                                                  ced_name_overrides.csv —
                                                  wiki_name → spc_name pairs
                                                  for any future drift)

Output: data/holyrood_winners.json — list of records:
        {"spc": "S16000151", "name": "Aberdeen Central",
         "winner": "SNP",    "year": 2026, "source": "wiki_2026"}

Parsing:
  The "Results of the 2026 Scottish Parliament election" article tabulates all
  73 FPTP seats in one wikitable inside === Constituencies ===. Each row's
  first cell is the constituency wikilink; remaining cells alternate party
  colour-strip + candidate cell (7 party columns: SNP / Labour / Conservative
  / Greens / Lib Dem / Reform UK / Other). The winning candidate's cell is
  highlighted with style="background:#FEFDDE;" — locate that cell and the
  *preceding* colour strip carries the party in its `{{party color|<NAME>}}`
  template, which feeds the canonical `normalize_party` mapper.

Coverage target: 73/73 with a winner. The script prints a summary line and
surfaces any unmatched / unparsed rows on stderr (per the "surface silent
join failures" rule).
"""
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
RAW = SOURCE / "wiki_holyrood_2026.json"
OVERRIDES = SOURCE / "holyrood_name_overrides.csv"
GEOMS = DATA / "ward_geoms.json"
OUT = DATA / "holyrood_winners.json"

# Five distinct highlight tones across the 73 rows (hold-yellow #FEFDDE plus a
# different shade per party-gain), so match any inline background colour rather
# than pinning to one hex. The colour-strip cells use `bgcolor=` (not
# `style="background:"`), so this regex alone separates winners from strips.
WINNER_BG_RE = re.compile(r'style="\s*background\s*:', re.IGNORECASE)
PARTY_COLOUR_RE = re.compile(r'\{\{\s*party\s+color\s*\|\s*([^}]+?)\s*\}\}', re.IGNORECASE)
WIKILINK_RE = re.compile(r'\[\[([^\]\|]+?)(?:\|([^\]]+))?\]\]')


def normalise_name(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', s.lower())


def load_overrides() -> dict[str, str]:
    """wiki_name (normalised) → spc_name. Empty when the override CSV is absent."""
    if not OVERRIDES.exists():
        return {}
    out = {}
    with OVERRIDES.open() as f:
        for row in csv.DictReader(f):
            wiki = row.get('wiki_name', '').strip()
            spc  = row.get('spc_name', '').strip()
            if wiki and spc:
                out[normalise_name(wiki)] = spc
    return out


def extract_constituencies_section(wt: str) -> str:
    """Return the body of the === Constituencies === H3 in the Results article."""
    m = re.search(r'\n===\s*Constituencies\s*===', wt)
    if not m:
        raise SystemExit('Could not find === Constituencies === header in '
                         f'{RAW.relative_to(ROOT)} — has the article structure changed?')
    rest = wt[m.end():]
    end_m = re.search(r'\n===\s*[^=]', rest)
    return rest[:end_m.start()] if end_m else rest


def parse_winners(section: str) -> list[tuple[str, str | None, str | None]]:
    """Walk the wikitable inside the Constituencies section and yield one
    tuple (seat_name, party, candidate) per row. party=None means the
    winner highlight wasn't found — caller surfaces it as a miss."""
    table_m = re.search(r'\n\{\|.*?\n\|\}', section, re.DOTALL)
    if not table_m:
        raise SystemExit('No wikitable found inside === Constituencies ===.')
    table = table_m.group(0)
    rows = re.split(r'\n\|-\s*\n', table)
    out = []
    # rows[0] is `{| class="wikitable sortable"\n! ... headers ...`; skip it.
    for row in rows[1:]:
        cells = [c.strip() for c in row.split('\n|') if c.strip() and c.strip() != '}']
        if not cells:
            continue
        # First cell: the seat name. It's a wikilink like [[Foo (Scottish ...)
        # |Foo]] or plain [[Foo]].
        link_m = WIKILINK_RE.search(cells[0])
        if not link_m:
            continue
        seat = (link_m.group(2) or link_m.group(1)).strip()

        # Walk remaining cells. Pairs are (colour-strip, candidate). The
        # candidate cell with WINNER_HIGHLIGHT is the winner; its
        # preceding colour-strip carries the party.
        prev_party_raw: str | None = None
        winner_party_raw: str | None = None
        winner_candidate: str | None = None
        for cell in cells[1:]:
            pm = PARTY_COLOUR_RE.search(cell)
            if pm and 'width="1"' in cell:
                # Colour strip — remember the party for the next candidate cell.
                prev_party_raw = pm.group(1).strip()
                continue
            if WINNER_BG_RE.search(cell):
                winner_party_raw = prev_party_raw
                # Extract candidate name (best-effort, for the tooltip).
                cm = WIKILINK_RE.search(cell)
                if cm:
                    winner_candidate = (cm.group(2) or cm.group(1)).strip()
                else:
                    # Plain text candidate — strip the bold markers + vote count.
                    txt = re.sub(r"'''", '', cell)
                    txt = re.sub(r'<br/?>.*$', '', txt, flags=re.DOTALL).strip()
                    txt = re.sub(r'^style="[^"]+"\s*\|\s*', '', txt)
                    winner_candidate = txt or None
                break  # one winner per row
        party = normalize_party(winner_party_raw) if winner_party_raw else None
        out.append((seat, party, winner_candidate))
    return out


def main():
    if not RAW.exists():
        raise SystemExit(f'{RAW.relative_to(ROOT)} not found — run '
                         'scripts/17_fetch_holyrood_results.py first.')
    raw = json.loads(RAW.read_text())
    wt = raw['parse']['wikitext']
    section = extract_constituencies_section(wt)

    rows = parse_winners(section)
    if len(rows) != 73:
        print(f'  WARN: parser returned {len(rows)} rows (expected 73). '
              f'Wikitable structure may have changed.', file=sys.stderr)

    # Geometry-side index: SPC26CD ↔ name.
    geoms = json.loads(GEOMS.read_text())
    spcs = geoms.get('spcs') or {}
    if not spcs:
        raise SystemExit(f'{GEOMS.relative_to(ROOT)} has no `spcs` key — run '
                         'scripts/09d_fetch_holyrood_boundaries.py first.')
    name_to_code = {normalise_name(s['name']): code for code, s in spcs.items()}
    overrides = load_overrides()

    records: list[dict] = []
    misses: list[tuple[str, str | None]] = []
    no_winner: list[str] = []
    for seat, party, _candidate in rows:
        spc_name = overrides.get(normalise_name(seat))
        if spc_name:
            code = name_to_code.get(normalise_name(spc_name))
        else:
            code = name_to_code.get(normalise_name(seat))
        if not code:
            misses.append((seat, party))
            continue
        if not party:
            no_winner.append(seat)
        records.append({
            'spc':    code,
            'name':   spcs[code]['name'],
            'winner': party,
            'year':   2026,
            'source': 'wiki_2026',
        })

    records.sort(key=lambda r: r['spc'])
    OUT.write_text(json.dumps(records, indent=2))

    n_total = len(records)
    n_with_winner = sum(1 for r in records if r['winner'])
    print(f'\nWrote {OUT.relative_to(ROOT)}: {n_total} constituencies '
          f'({n_with_winner} with winner; {n_total - n_with_winner} grey)')
    if misses:
        print(f'\n  WARN: {len(misses)} wiki seat(s) did not match any SPC26 polygon '
              f'— add a row to data/source/holyrood_name_overrides.csv:', file=sys.stderr)
        for seat, party in misses:
            print(f'    "{seat}"  (party: {party})', file=sys.stderr)
    if no_winner:
        print(f'\n  WARN: {len(no_winner)} matched seat(s) had no parseable winner '
              f'cell:', file=sys.stderr)
        for seat in no_winner:
            print(f'    {seat}', file=sys.stderr)


if __name__ == '__main__':
    main()
