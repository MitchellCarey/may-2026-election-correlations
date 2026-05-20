"""Parse the cached Electoral Commission EU referendum CSV
(data/source/ec_eu_referendum_2016.csv) and emit data/eu_ref_2016.json
in the project's standard history-JSON shape.

Reads:  data/source/ec_eu_referendum_2016.csv  (cached by scripts/25)
Writes: data/eu_ref_2016.json

Output schema (mirrors data/ge_history.json / data/holyrood_history.json
so 07d can carry-forward / paint with the same logic):

  {
    "years": [2016],
    "lads": {
      "<LAD16CD>": {
        "name": "Hartlepool",
        "history": [{
          "y":     2016,
          "w":     "Leave" | "Remain",
          "src":   "electoral_commission",
          "url":   "https://www.electoralcommission.org.uk/...",
          "votes": {"Leave": 32071, "Remain": 14029},
          "pct":   {"Leave": 0.6951, "Remain": 0.3049}
        }]
      }
    }
  }

Per-record `pct` is pre-computed at extract time as a small convenience —
07d's tooltip wants "Leave 53.4% / Remain 46.6%" formatted directly, and
keeping the percentage in Python avoids re-floating the totals in JS on
every hover.

Filter: NI (1 counting area, N92000002) and Gibraltar (GI) are filtered
because the `gb` viewBox excludes them. Same option-1 treatment as
PCON 2024's NI seats in scripts/20_extract_ge2024.py.

Bootstrapped by issue #85 (EU Ref 2016 LAD-level overlay).
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CSV_PATH = DATA / "source" / "ec_eu_referendum_2016.csv"
OUT = DATA / "eu_ref_2016.json"

# Click-through URL for the renderer's tooltip "Source: …" line. Lands
# the reader on the EC results landing page from which the CSV downloads;
# the EC doesn't host a per-LAD permalink so the same URL is attached to
# every record. The CSV link itself is on this page.
SOURCE_URL = (
    'https://www.electoralcommission.org.uk/'
    'who-we-are-and-what-we-do/elections-and-referendums/'
    'past-elections-and-referendums/eu-referendum/'
    'results-and-turnout-eu-referendum'
)

YEAR = 2016

# GB-only LAD prefixes — same set 07d filters on for the wards layer.
# The EC CSV uses 2016-era LAD codes (E07000048 Christchurch, E07000190
# Taunton Deane, etc.) which is what we want: 27_fetch_lad_2016_geoms.py
# fetches the matching boundary set so each 2016 counting area paints on
# its own 2016-vintage polygon.
GB_LAD_PREFIXES = ('E06', 'E07', 'E08', 'E09', 'W06', 'S12')


def parse_row(row: dict) -> tuple[str, str, dict | None, str | None]:
    """Parse one Electoral Commission CSV row into a per-LAD record.

    Returns (code, name, record, skip_reason). When skip_reason is None the
    record is populated and should be kept; otherwise record is None and
    skip_reason is one of 'non_gb', 'invalid_votes', 'zero_votes'.
    Pure function — no I/O, callers handle logging.
    """
    code = (row.get('Area_Code') or '').strip()
    name = (row.get('Area') or '').strip()

    # Skip NI (single counting area: N92000002) and Gibraltar (counted in
    # the SW region but reported as a separate row with the synthetic
    # "GI" code). Both fall outside the gb viewBox in 07d.
    if not code.startswith(GB_LAD_PREFIXES):
        return code, name, None, 'non_gb'

    try:
        leave = int(row['Leave'])
        remain = int(row['Remain'])
    except (KeyError, TypeError, ValueError):
        return code, name, None, 'invalid_votes'

    total = leave + remain
    if total <= 0:
        return code, name, None, 'zero_votes'

    # Plurality winner. EU ref had no ties in 2016 — the closest GB
    # result was Manchester (60.4% Remain), well above any rounding
    # boundary. Still defensive in case a future referendum (#84 / #86)
    # hits a precise tie; ties default to Remain.
    winner = 'Leave' if leave > remain else 'Remain'

    record = {
        'name': name,
        'history': [{
            'y':     YEAR,
            'w':     winner,
            'src':   'electoral_commission',
            'url':   SOURCE_URL,
            'votes': {'Leave': leave, 'Remain': remain},
            'pct':   {
                'Leave':  round(leave  / total, 4),
                'Remain': round(remain / total, 4),
            },
        }],
    }
    return code, name, record, None


def main():
    if not CSV_PATH.exists():
        raise SystemExit(
            f"{CSV_PATH.relative_to(ROOT)} not found — run scripts/25 first.")

    lads: dict[str, dict] = {}
    filtered: list[tuple[str, str]] = []  # (code, reason)

    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code, name, record, skip = parse_row(row)
            if skip == 'non_gb':
                filtered.append((code, name))
                continue
            if skip == 'invalid_votes':
                print(f'  WARN: {code} {name}: could not parse Leave/Remain',
                      file=sys.stderr)
                continue
            if skip == 'zero_votes':
                print(f'  WARN: {code} {name}: zero-vote row — skipping',
                      file=sys.stderr)
                continue
            if record['history'][0]['votes']['Leave'] == \
               record['history'][0]['votes']['Remain']:
                print(f'  WARN: {code} {name}: exact tie — defaulting to Remain',
                      file=sys.stderr)
            lads[code] = record

    out = {'years': [YEAR], 'lads': lads}
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))

    # Per-prefix tally — the user-facing diagnostic. 326 + 22 + 32 = 380.
    by_prefix: dict[str, int] = {}
    leave_wins = remain_wins = 0
    for code, lad in lads.items():
        prefix = code[:3]
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
        if lad['history'][0]['w'] == 'Leave':
            leave_wins += 1
        else:
            remain_wins += 1
    prefix_line = ', '.join(f'{p}={n}' for p, n in sorted(by_prefix.items()))

    print(f'\nWrote {OUT.relative_to(ROOT)} — {len(lads)} GB LADs '
          f'({prefix_line})')
    print(f'  Leave plurality: {leave_wins}; Remain plurality: {remain_wins}')

    if filtered:
        print(f'  Filtered {len(filtered)} non-GB counting area(s):',
              file=sys.stderr)
        for code, name in filtered:
            print(f'    {code} {name}', file=sys.stderr)


if __name__ == '__main__':
    main()
