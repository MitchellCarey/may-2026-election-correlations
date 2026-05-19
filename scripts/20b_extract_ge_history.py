"""Extract per-PCON × per-year winners from the House of Commons Library
1918-2019 General Election dataset (CBP-8647) and emit data/ge_history.json.

Reads: data/source/hoc_ge_1918_2019_by_pcon.xlsx  (cached by scripts/19b)
Writes: data/ge_history.json

Output schema — keyed by ONS PCON code (PCON10/15/19CD code space, which is
identical for these three elections since Westminster boundaries did not
change between 2010 and the July 2024 review):

  {
    "years": [2015, 2017, 2019],
    "pcons": {
      "<PCON_DEC_2021_code>": {
        "name": "...",
        "history": [
          {"y": 2015, "w": "Labour", "candidate": null, "src": "hoc",
           "url": "https://commonslibrary.parliament.uk/research-briefings/cbp-8647/",
           "votes": {"Labour": 23322, "Conservative": 18792, ...}},
          ...
        ]
      }
    }
  }

Match-mirrors data/holyrood_history.json / data/senedd_history.json so 07d
can consume it with the same paintAtYear shape.

Why HoC and not Wikipedia: the project's accuracy hierarchy (CLAUDE.md top
section) puts HoC Library at tier 2 (above Wikipedia) because it is
collected directly from Returning Officers, cross-checked, and publicly
audited. Wikipedia per-constituency Election boxes transcribe the same
upstream data with the additional risk of editorial drift; we use them
as a fallback when HoC has gaps, but HoC's 2015/2017/2019 coverage is
already 650/650 so no fallback is invoked today.

Per-sheet layout in the XLSX (consistent across 2015 / 2017 / 2019, with
column shifts between years for party order — Conservative col 8 in all
three, but the next 12 party-group columns vary):

  row 1-2: title rows ("YYYY GENERAL ELECTION" / "Results by constituency")
  row 3:   party-group headers ("Conservative", "Liberal Democrats", etc.) —
           positions vary year-on-year. The 'id' header lives in row 3 for
           2015 and in row 4 for 2017/2019.
  row 4:   sub-headers ('Constituency', 'County', 'Country/Region',
           'Country', 'Electorate', then per-party 'Votes' / 'Vote share'
           pairs). 'id' lives here in 2017/2019.
  row 5+:  data rows (650 GB+NI rows ending at row 654; rows 655+ are
           footnotes — filter by code prefix to skip).

Speaker seats are detected via a small hand-curated override map:
Buckingham 2015 & 2017 (John Bercow), Chorley 2019 (Lindsay Hoyle). HoC
classifies their votes under "Other" in the simple-table view; without
the override, the renderer would paint these three (code, year) pairs
with the "Other" palette colour and lose the Speaker label. North Down
(Sylvia Hermon, Independent 2015 & 2017) is N05* → filtered out at render
time, no override needed.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
XLSX = DATA / "source" / "hoc_ge_1918_2019_by_pcon.xlsx"
OUT = DATA / "ge_history.json"

YEARS = (2015, 2017, 2019)

# Stable across all three sheets — only England, Wales, Scotland, NI PCON
# code prefixes flag real data rows. Everything else (footnotes,
# region-name expansion notes) is filtered out.
GB_PREFIXES = ('E14', 'W07', 'S14')
ALL_PREFIXES = GB_PREFIXES + ('N06',)  # NI in dataset is N06xxxxxx for 2010 codes

# Source attribution for every history entry. The briefing page is what
# 07d's tooltip will link to when a reader clicks through to verify.
SOURCE_URL = 'https://commonslibrary.parliament.uk/research-briefings/cbp-8647/'

# Speaker overrides: (PCON10/15CD, year) → (winner_label, candidate_name).
# These are the only three (constituency, year) pairs in GB where the
# elected MP sat as Speaker rather than under their original party — HoC
# folds their votes into "Other" in the per-PCON view, so without these
# overrides the renderer would paint them with the Other palette colour
# and lose the Speaker distinction.
SPEAKER_OVERRIDES: dict[tuple[str, int], tuple[str, str]] = {
    ('E14000608', 2015): ('Speaker', 'John Bercow'),
    ('E14000608', 2017): ('Speaker', 'John Bercow'),
    ('E14000637', 2019): ('Speaker', 'Lindsay Hoyle'),
}


def detect_party_columns(ws) -> dict[int, str]:
    """Scan row 3 for party-group headers ('Conservative' / 'Labour' etc.).
    Returns {column_index → raw_party_label}. Columns NOT mapped here are
    candidate-vote columns (the 'Votes' sub-header in row 4); we use the
    party_label that immediately precedes each Votes column. Same shape
    across all three target sheets — only the column *positions* differ
    (2015 = Con/LD/Lab/UKIP/...; 2019 = Con/Lab/LD/Brexit/...)."""
    party_row = ws[3]  # 1-indexed; row 3 is the party-group header
    out: dict[int, str] = {}
    for cell in party_row:
        v = cell.value
        if v and isinstance(v, str) and v.strip():
            # Column header is the party label; the 'Votes' cell sits at
            # the same column in row 4. So col is shared. Skip 'id' here.
            label = v.strip()
            if label.lower() == 'id':
                continue
            out[cell.column] = label
    return out


def find_id_column(ws) -> int:
    """The 'id' header lives in row 3 for the 2015 sheet, row 4 for 2017
    and 2019. Scan both rows for a cell whose stripped value lowercases
    to 'id' (or 'ons id', 2019's variant) and return its column index."""
    for row_idx in (3, 4):
        for cell in ws[row_idx]:
            v = cell.value
            if v and isinstance(v, str) and v.strip().lower() in ('id', 'ons id'):
                return cell.column
    raise SystemExit(f"no 'id' column found in row 3 or 4 of sheet {ws.title}")


# CSV → JSON party-key normalisation. Returns the canonical label that
# 07d's palette + display maps already know about. UKIP / Brexit / DUP /
# Sinn Féin / SDLP / UUP / Alliance all fold to 'Other' — consistent with
# 20_extract_ge2024.py's westminster_party() wrapper. Speaker is preserved
# by the overrides map above, not by this normaliser.
def normalize_hoc_party(raw: str) -> str:
    s = raw.strip()
    # Trailing whitespace in source headers — "Labour " (2017), etc.
    s = ' '.join(s.split())
    return normalize_party(s)


def parse_sheet(ws, year: int) -> list[dict]:
    """Return one record per data row in the sheet. Filters to rows whose
    'id' cell holds a real ONS code (E14*/W07*/S14*/N06*); everything
    else (footer rows) is skipped."""
    id_col = find_id_column(ws)
    party_cols = detect_party_columns(ws)
    # Sorted columns so we can read votes deterministically.
    party_col_list = sorted(party_cols.items())  # [(col, label), ...]
    name_col = 3  # 'Constituency' lives at col C consistently

    records: list[dict] = []
    misses: list[str] = []

    # iter from row 5 onwards (data starts at row 5; 4 is sub-header).
    for row in ws.iter_rows(min_row=5, max_row=ws.max_row, values_only=False):
        id_cell = row[id_col - 1] if id_col - 1 < len(row) else None
        code = (id_cell.value or '') if id_cell else ''
        if not isinstance(code, str):
            continue
        code = code.strip()
        if not code.startswith(ALL_PREFIXES):
            continue

        name_cell = row[name_col - 1] if name_col - 1 < len(row) else None
        name = (name_cell.value or '').strip() if name_cell and isinstance(name_cell.value, str) else ''

        # Per-party votes — read each party column. The 'Votes' cell sits
        # at the same column index as the party-group header in row 3.
        votes_raw: dict[str, int] = {}
        for col, label in party_col_list:
            cell = row[col - 1] if col - 1 < len(row) else None
            v = cell.value if cell else None
            if v is None:
                continue
            # Numbers in the XLSX may come back as int or float; cast and
            # round to int to match Wikipedia / Returning Officer convention.
            try:
                n = int(round(float(v)))
            except (TypeError, ValueError):
                continue
            if n <= 0:
                continue
            votes_raw[label] = n

        if not votes_raw:
            misses.append(f'{code} {name} ({year}): no party votes parsed')
            continue

        # Pick the raw winner — the party-group label with the most votes.
        # On the (vanishingly rare) tie, `max` returns the first
        # iteration-order entry; emit a stderr WARN so a real tie is at
        # least visible in the build log.
        sorted_votes = sorted(votes_raw.items(), key=lambda kv: kv[1], reverse=True)
        raw_winner_label, top_votes = sorted_votes[0]
        if len(sorted_votes) > 1 and sorted_votes[1][1] == top_votes:
            tied = [lbl for lbl, n in sorted_votes if n == top_votes]
            print(f'  WARN: {code} {name} ({year}): vote tie at {top_votes:,} '
                  f'between {", ".join(tied)} — picked {raw_winner_label}',
                  file=sys.stderr)

        # Speaker override beats whatever the votes-max said.
        override = SPEAKER_OVERRIDES.get((code, year))
        if override:
            winner_party, candidate = override
        else:
            winner_party = normalize_hoc_party(raw_winner_label)
            candidate = None

        # Per-record votes dict — collapse raw labels to canonical via
        # the same normaliser so the palette keys line up with ge2024.json.
        votes_canon: dict[str, int] = {}
        for label, n in votes_raw.items():
            key = normalize_hoc_party(label)
            votes_canon[key] = votes_canon.get(key, 0) + n

        records.append({
            'code':      code,
            'name':      name.title() if name.isupper() else name,
            'y':         year,
            'w':         winner_party,
            'candidate': candidate,
            'src':       'hoc',
            'url':       SOURCE_URL,
            'votes':     votes_canon,
        })

    for m in misses:
        print(f'  WARN: {m}', file=sys.stderr)
    return records


def main():
    if not XLSX.exists():
        raise SystemExit(
            f"{XLSX.relative_to(ROOT)} not found — run scripts/19b first.")

    wb = load_workbook(XLSX, read_only=True, data_only=True)
    all_records: list[dict] = []
    for year in YEARS:
        if str(year) not in wb.sheetnames:
            raise SystemExit(f"sheet {year} missing from {XLSX.name}")
        ws = wb[str(year)]
        rows = parse_sheet(ws, year)
        # Sanity: HoC ships 650 rows per year (632 GB + 18 NI). A drop
        # below 650 means the parser tripped on a footer row or the sheet
        # layout changed.
        if len(rows) != 650:
            print(f'  WARN: sheet {year} parsed {len(rows)} rows '
                  f'(expected 650)', file=sys.stderr)
        all_records.extend(rows)

    # Pivot to per-PCON shape. Each PCON's history is sorted ascending
    # by year so paintAtYear's carry-forward loop can short-circuit.
    pcons: dict[str, dict] = {}
    for r in all_records:
        code = r['code']
        if code not in pcons:
            pcons[code] = {'name': r['name'], 'history': []}
        pcons[code]['history'].append({
            'y':         r['y'],
            'w':         r['w'],
            'candidate': r['candidate'],
            'src':       r['src'],
            'url':       r['url'],
            'votes':     r['votes'],
        })
    for code, p in pcons.items():
        p['history'].sort(key=lambda e: e['y'])

    out = {'years': list(YEARS), 'pcons': pcons}
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))

    # Summary stats — same diagnostic shape as 04e_build_ced_history /
    # 04f_build_holyrood_history etc.
    gb_pcons = [c for c in pcons if c.startswith(GB_PREFIXES)]
    ni_pcons = [c for c in pcons if c.startswith('N06')]
    total_entries = sum(len(p['history']) for p in pcons.values())

    print(f'\nWrote {OUT.relative_to(ROOT)} — '
          f'{len(pcons)} PCONs ({len(gb_pcons)} GB + {len(ni_pcons)} NI), '
          f'{total_entries:,} PCON-years across {len(YEARS)} year stops.')

    # Per-year per-party tally on the GB subset — the user-facing diagnostic.
    for year in YEARS:
        winners = Counter(
            entry['w']
            for code, p in pcons.items() if code.startswith(GB_PREFIXES)
            for entry in p['history'] if entry['y'] == year
        )
        line = ', '.join(f'{p} {n}' for p, n in winners.most_common())
        print(f'  GE {year} GB winners: {line}')


if __name__ == '__main__':
    main()
