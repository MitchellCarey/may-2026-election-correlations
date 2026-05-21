"""Parse the cached Wikipedia wikitext for the 18 September 2014 Scottish
independence referendum and emit data/indyref_2014.json in the project's
standard history-JSON shape.

Reads:  data/source/wiki_indyref_2014.json   (cached by scripts/29)
Writes: data/indyref_2014.json

Output schema (mirrors data/eu_ref_2016.json so 07d carries-forward / paints
with the same logic — and the slider's YEARS array unions the `years`
list across every history source):

  {
    "years": [2014],
    "lads": {
      "<S12CD>": {
        "name": "Glasgow City",
        "history": [{
          "y":     2014,
          "w":     "Yes" | "No",
          "src":   "wikipedia",
          "url":   "https://en.wikipedia.org/wiki/2014_Scottish_independence_referendum",
          "votes": {"Yes": 194779, "No": 169347},
          "pct":   {"Yes": 0.5348, "No": 0.4652}
        }]
      }
    }
  }

Sourcing note: the EC published the indyref per-counting-area numbers
only inside the Scottish-independence-referendum-report.pdf (Appendix 3)
— no machine-readable companion. The Wikipedia table in
"2014 Scottish independence referendum" is sourced from that EC return.
The validation block below cross-checks every parsed row against the
known EC totals (Yes 1,617,989 / No 2,001,926; 4 Yes councils, 28 No
councils) so any future silent wikitext drift surfaces as a hard
failure, not a quietly wrong map.

Issue #86. Companions: scripts/29_fetch_indyref.py.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "source" / "wiki_indyref_2014.json"
OUT = DATA / "indyref_2014.json"

# Source URL used for the renderer tooltip's "Source: …" line and for
# the click-through that opens the canonical article. The Wikipedia
# article footer cites the Electoral Commission return — readers who
# want the primary PDF land on it via the article's reference list.
SOURCE_URL = (
    'https://en.wikipedia.org/wiki/2014_Scottish_independence_referendum'
)

YEAR = 2014

# Wikipedia per-council label → ONS LAD24 S12 code. Most rows match the
# borough name in data/ward_geoms.json verbatim; the 6 mismatches are
# explicit here so a future Wikipedia rename surfaces during the join
# rather than silently producing a 0-row output.
#
# Cross-checked against ward_geoms.boroughs (32 S12 entries) on 2026-05-21.
WIKI_NAME_TO_S12: dict[str, str] = {
    'Aberdeen':                'S12000033',  # → "Aberdeen City"
    'Aberdeenshire':           'S12000034',
    'Angus':                   'S12000041',
    'Argyll and Bute':         'S12000035',
    'Clackmannanshire':        'S12000005',
    'Dumfries and Galloway':   'S12000006',
    'Dundee':                  'S12000042',  # → "Dundee City"
    'East Ayrshire':           'S12000008',
    'East Dunbartonshire':     'S12000045',
    'East Lothian':            'S12000010',
    'East Renfrewshire':       'S12000011',
    'Edinburgh':               'S12000036',  # → "City of Edinburgh"
    'Eilean Siar':             'S12000013',  # → "Na h-Eileanan Siar"
    'Falkirk':                 'S12000014',
    'Fife':                    'S12000047',
    'Glasgow':                 'S12000049',  # → "Glasgow City"
    'Highland':                'S12000017',
    'Inverclyde':              'S12000018',
    'Midlothian':              'S12000019',
    'Moray':                   'S12000020',
    'North Ayrshire':          'S12000021',
    'North Lanarkshire':       'S12000050',
    'Orkney':                  'S12000023',  # → "Orkney Islands"
    'Perth and Kinross':       'S12000048',
    'Renfrewshire':            'S12000038',
    'Scottish Borders':        'S12000026',
    'Shetland':                'S12000027',  # → "Shetland Islands"
    'South Ayrshire':          'S12000028',
    'South Lanarkshire':       'S12000029',
    'Stirling':                'S12000030',
    'West Dunbartonshire':     'S12000039',
    'West Lothian':            'S12000040',
}
assert len(WIKI_NAME_TO_S12) == 32, 'Scottish council count must be 32'
assert len(set(WIKI_NAME_TO_S12.values())) == 32, 'S12 codes must be unique'

# EC headline totals (Yes 44.7% / No 55.3%, turnout 84.59%). Sourced from
# the EC report Scottish-independence-referendum-report.pdf p.4. Used by
# the validation block at the bottom of the extractor to fail hard if a
# future wikitext edit corrupts the table.
EXPECTED_YES_TOTAL = 1_617_989
EXPECTED_NO_TOTAL = 2_001_926
EXPECTED_YES_COUNCILS = 4   # Dundee, Glasgow, N Lanarkshire, W Dunbartonshire
EXPECTED_NO_COUNCILS = 28

# Wikipedia row anchor — the line immediately preceding the council name.
# The table starts right after the header row ending "Turnout (%)\n|-".
TABLE_START_MARKER = 'Turnout (%)\n|-'
TABLE_END_MARKERS = ('|}', '\n==')


def split_rows(body: str) -> list[str]:
    return [r.strip() for r in body.split('|-') if r.strip()]


# Wikipedia's table row body. Capture group:
#   1: council display name as it appears between |scope="row" …| and EOL
ROW_NAME_RE = re.compile(
    r'\|scope="row"\s*style="text-align:left"\|(.+?)(?=\n)',
    re.MULTILINE,
)


def strip_wikilinks(s: str) -> str:
    """[[Page|Display]] → Display ; [[Page]] → Page."""
    s = re.sub(r'\[\[([^\|\]]+)\|([^\]]+)\]\]', r'\2', s)
    s = re.sub(r'\[\[([^\]]+)\]\]', r'\1', s)
    return s.strip()


def parse_row(row: str) -> tuple[str, int, int, str | None] | None:
    """Return (display_name, yes_votes, no_votes, error) or None on no-match.

    Detects the winner from the '''bold''' markup the wikitable applies to
    the winning vote count, with a numeric fallback (Yes / No).
    """
    m = ROW_NAME_RE.search(row)
    if not m:
        return None
    name = strip_wikilinks(m.group(1))

    # Pull each "| <cell>" segment as a list. Cells with template wrappers
    # like {{No|'''58.6%'''|align=right}} are kept intact so the bold
    # detection sees the triple quotes.
    cells_raw = [c.strip() for c in re.split(r'\n\|', '\n' + row) if c.strip()]
    # Skip the leading row-header cell (the name we already parsed). The
    # remaining cells should be: Yes votes, No votes, Yes %, No %, Valid
    # votes, Turnout %.
    cells = [c for c in cells_raw if not c.startswith('scope="row"')]
    if len(cells) < 2:
        return name, 0, 0, 'too_few_cells'

    yes_cell, no_cell = cells[0], cells[1]

    # Numeric vote counts — first \d[\d,]* in each cell.
    def first_int(cell: str) -> int | None:
        m = re.search(r'\b(\d[\d,]*)\b', cell)
        return int(m.group(1).replace(',', '')) if m else None

    yes = first_int(yes_cell)
    no = first_int(no_cell)
    if yes is None or no is None:
        return name, yes or 0, no or 0, 'unparseable_votes'

    return name, yes, no, None


def main():
    if not CACHE.exists():
        raise SystemExit(f'{CACHE.relative_to(ROOT)} not found — run '
                         f'scripts/29 first.')
    payload = json.loads(CACHE.read_text())
    wt = payload.get('parse', {}).get('wikitext')
    if not wt:
        raise SystemExit('cached wikitext payload has no parse.wikitext')

    i = wt.find(TABLE_START_MARKER)
    if i < 0:
        raise SystemExit('Wikipedia results table not found — Wikipedia may '
                         'have restructured the article. Inspect '
                         f'{CACHE.relative_to(ROOT)} and update '
                         f'TABLE_START_MARKER.')
    body = wt[i + len(TABLE_START_MARKER):]
    end = min((body.find(m) for m in TABLE_END_MARKERS if body.find(m) > 0),
              default=len(body))
    body = body[:end]

    lads: dict[str, dict] = {}
    seen_names: set[str] = set()
    misses: list[tuple[str, str]] = []

    for raw_row in split_rows(body):
        parsed = parse_row(raw_row)
        if parsed is None:
            continue
        name, yes, no, err = parsed
        if err:
            print(f'  WARN: {name}: {err}', file=sys.stderr)
            continue
        s12 = WIKI_NAME_TO_S12.get(name)
        if not s12:
            misses.append((name, 'no S12 mapping'))
            continue
        if name in seen_names:
            print(f'  WARN: duplicate row for {name}; keeping first',
                  file=sys.stderr)
            continue
        seen_names.add(name)

        total = yes + no
        if total <= 0:
            print(f'  WARN: {name}: zero votes', file=sys.stderr)
            continue
        winner = 'Yes' if yes > no else 'No'
        lads[s12] = {
            'name': name,
            'history': [{
                'y':     YEAR,
                'w':     winner,
                'src':   'wikipedia',
                'url':   SOURCE_URL,
                'votes': {'Yes': yes, 'No': no},
                'pct':   {
                    'Yes': round(yes / total, 4),
                    'No':  round(no  / total, 4),
                },
            }],
        }

    # Cross-check against the known EC totals. Hard-fail on drift so a
    # bad upstream edit doesn't ship a wrong-looking map.
    yes_total = sum(l['history'][0]['votes']['Yes'] for l in lads.values())
    no_total = sum(l['history'][0]['votes']['No']  for l in lads.values())
    yes_wins = sum(1 for l in lads.values() if l['history'][0]['w'] == 'Yes')
    no_wins = sum(1 for l in lads.values() if l['history'][0]['w'] == 'No')

    problems: list[str] = []
    if len(lads) != 32:
        problems.append(f'expected 32 councils, got {len(lads)}')
    if yes_total != EXPECTED_YES_TOTAL:
        problems.append(
            f'Yes total {yes_total:,} != expected {EXPECTED_YES_TOTAL:,}'
        )
    if no_total != EXPECTED_NO_TOTAL:
        problems.append(
            f'No total {no_total:,} != expected {EXPECTED_NO_TOTAL:,}'
        )
    if yes_wins != EXPECTED_YES_COUNCILS:
        problems.append(
            f'Yes-winning councils {yes_wins} != expected '
            f'{EXPECTED_YES_COUNCILS}'
        )
    if no_wins != EXPECTED_NO_COUNCILS:
        problems.append(
            f'No-winning councils {no_wins} != expected '
            f'{EXPECTED_NO_COUNCILS}'
        )
    if misses:
        problems.append(f'unmapped Wikipedia council names: {misses!r}')
    if problems:
        for p in problems:
            print(f'  FAIL: {p}', file=sys.stderr)
        raise SystemExit(
            'Indyref extraction failed cross-check against EC totals. '
            'Refusing to write data/indyref_2014.json.'
        )

    out = {'years': [YEAR], 'lads': lads}
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))

    print(f'\nWrote {OUT.relative_to(ROOT)} — {len(lads)} Scottish councils')
    print(f'  Yes-winning ({yes_wins}): '
          + ', '.join(sorted(l['name'] for l in lads.values()
                             if l['history'][0]['w'] == 'Yes')))
    print(f'  No-winning  ({no_wins})')
    yes_pct = yes_total / (yes_total + no_total)
    no_pct = no_total / (yes_total + no_total)
    print(f'  Totals: Yes {yes_total:,} ({yes_pct:.1%}) / '
          f'No {no_total:,} ({no_pct:.1%})')


if __name__ == '__main__':
    main()
