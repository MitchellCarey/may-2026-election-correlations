"""Parse the 11 cached per-constituency Wikipedia articles fetched by
scripts/29_fetch_eu_parliament.py and emit one history-shaped JSON with
per-region per-year d'Hondt seat allocations + vote totals for the
2014 + 2019 European Parliament elections (issue #91).

Output: data/ep_results.json — keyed by EER code, history shape mirroring
holyrood_history.json / senedd_history.json:

  {
    "years": [2014, 2019],
    "regions": {
      "E15000001": {
        "name": "North East England",
        "history": [
          {"y": 2014, "w": "Labour", "src": "wikipedia", "url": "...",
           "seats":     {"Labour": 2, "UKIP": 1},
           "seats_raw": {"Labour Party (UK)": 2, "UK Independence Party": 1},
           "votes":     {"Labour": 221988, "UKIP": 177660, ...}},
          {"y": 2019, "w": "Brexit", "src": "wikipedia", "url": "...",
           "seats":     {"Brexit": 2, "Labour": 1},
           "seats_raw": {"Brexit Party": 2, "Labour Party (UK)": 1},
           "votes":     {...}}
        ]
      },
      ...
    }
  }

Parser notes:

Each per-constituency article carries one H3 `=== YYYY ===` per contest
inside the `== Election results ==` H2. Each year section contains a
single `{{Election box begin for list|title=...}}` block closed by
`{{Election box end}}`, with one `{{Election box candidate with party
link|...|party=PARTY|candidate='''Bold Name''' (1) <br /> ...|votes=N|
percentage=...|change=...}}` row per contesting party.

Seat allocation: count `'''...'''` (triple-quoted) bold spans inside the
`candidate=` field. The Wikipedia convention is that elected MEPs are
shown in bold with their seat-rank in parentheses; non-elected list
candidates are shown in `<small>...</small>`. So `bold-count per party =
seats won under d'Hondt`. Sum across all parties = total EER seat count
(3 for North East, 8 for North West, ..., 10 for South East, 6 for
Scotland, 4 for Wales — 70 GB seats total at both 2014 and 2019).

Votes: read the `votes=N,NNN` field on each party row.

Plurality winner: party with the highest vote total (note: this is the
plurality vote winner, which under d'Hondt usually but not always matches
the largest seat count — for North East 2019, Brexit Party won 2 seats
with 240,056 votes, ahead of Labour's 1 seat with 119,931 votes).
"""
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _eu_parliament import EU_PARLIAMENT_REGIONS, TARGET_YEARS
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "ep_results.json"

# `=== YYYY ===` per-contest section header inside `== Election results ==`.
# Allow 2-4 equals signs (most articles use 3; defensive against 2-equals
# alternates).
YEAR_HEADER_RE = re.compile(r'^={2,4}\s*(\d{4})\s*={2,4}\s*$', re.MULTILINE)

# `{{Election box begin for list|title=...}}` opens the per-year results
# block. Some articles use the plain `{{Election box begin|title=...}}`
# (the EP-specific variant is unique to "for list" but accept both).
EB_BEGIN_RE = re.compile(
    r'\{\{\s*Election box begin(?:\s+for\s+list)?\b',
    re.IGNORECASE,
)
EB_END_RE = re.compile(r'\{\{\s*Election box end\s*\}\}', re.IGNORECASE)

# Opening marker for a candidate row. Body is read with a brace-balanced
# scanner below (iter_candidate_bodies) because some 2019 rows nest two
# levels of templates inside `change=` (e.g. `change={{nowrap|{{increase}}
# 32.46}}`) — Wales 2019 Brexit Party is the canonical example. A regex
# with a single level of nesting (the simpler pattern used by 15) fails
# to match those rows and silently drops them from the seat count.
# Mirrors 15b_extract_senedd_history.py::iter_candidate_bodies.
CANDIDATE_OPEN_RE = re.compile(
    r'\{\{\s*Election box candidate(?:\s+with\s+party\s+link)?\b',
    re.IGNORECASE,
)

PARTY_FIELD_RE = re.compile(r'\|\s*party\s*=\s*([^|\n]+)')
VOTES_FIELD_RE = re.compile(r'\|\s*votes\s*=\s*([\d,]+)')
# Candidate field can span multiple lines; capture until the next pipe
# *that introduces a known sibling field* so embedded `|` in wikilinks
# don't truncate. The candidate field always sits between `party=` and
# `votes=`, so the safest non-greedy stop is the next sibling marker.
CANDIDATE_FIELD_RE = re.compile(
    r'\|\s*candidate\s*=\s*(.*?)'
    r'(?=\|(?:votes|percentage|change|notes|won|loss|colour|color)\s*=)',
    re.IGNORECASE | re.DOTALL,
)
# `'''Bold Name''' (N)` — the bold span marks an elected MEP. We just
# count the spans per `candidate=` field; the (N) ranking is
# informational only. Use a lazy `.+?` (DOTALL) rather than `[^']+?`
# because candidate names contain literal apostrophes ("O'Flynn",
# "O'Connor") that the negated-class form treats as the closing quote
# and silently truncates the span — under-counting that party's seats.
BOLD_SPAN_RE = re.compile(r"'''.+?'''", re.DOTALL)


def wiki_url(title: str) -> str:
    return ('https://en.wikipedia.org/wiki/'
            + urllib.parse.quote(title.replace(' ', '_'), safe='_,()/'))


def extract_year_block(wt: str, year: int) -> str | None:
    """Find the `=== YYYY ===` section, then return the substring spanning
    its single Election-box block. None if no block found."""
    headers = [(m.start(), m.end(), int(m.group(1)))
               for m in YEAR_HEADER_RE.finditer(wt)]
    for i, (_hs, he, y) in enumerate(headers):
        if y != year:
            continue
        next_start = headers[i + 1][0] if i + 1 < len(headers) else len(wt)
        section = wt[he:next_start]
        bm = EB_BEGIN_RE.search(section)
        if not bm:
            return None
        em = EB_END_RE.search(section, bm.end())
        if not em:
            return None
        return section[bm.start():em.end()]
    return None


def iter_candidate_bodies(block_text: str):
    """Yield the body of each `{{Election box candidate ...}}` template,
    walking braces depth-aware so two-level nesting inside `change=` etc.
    doesn't break the scan. Mirrors 15b_extract_senedd_history.py."""
    for m in CANDIDATE_OPEN_RE.finditer(block_text):
        i = m.end()
        depth = 1
        n = len(block_text)
        while i < n - 1 and depth > 0:
            if block_text[i] == '{' and block_text[i + 1] == '{':
                depth += 1
                i += 2
            elif block_text[i] == '}' and block_text[i + 1] == '}':
                depth -= 1
                if depth == 0:
                    yield block_text[m.end():i]
                    i += 2
                    break
                i += 2
            else:
                i += 1


def parse_year_block(block: str) -> tuple[dict, dict, dict] | None:
    """Return (seats_normalised, seats_raw, votes_normalised) or None if
    no candidate rows parsed. votes are int totals per normalised party."""
    seats: dict[str, int] = {}
    seats_raw: dict[str, int] = {}
    votes: dict[str, int] = {}
    for body in iter_candidate_bodies(block):
        pm = PARTY_FIELD_RE.search(body)
        vm = VOTES_FIELD_RE.search(body)
        cm = CANDIDATE_FIELD_RE.search(body)
        if not pm:
            continue
        raw_party = pm.group(1).strip()
        party = normalize_party(raw_party)
        # Vote total (a few rows may have empty/blank votes — skip them
        # but still count seats if any).
        if vm:
            try:
                v = int(vm.group(1).replace(',', ''))
                votes[party] = votes.get(party, 0) + v
            except ValueError:
                pass
        # Seat count = bold spans in candidate field.
        bold = 0
        if cm:
            bold = len(BOLD_SPAN_RE.findall(cm.group(1)))
        if bold:
            seats[party] = seats.get(party, 0) + bold
            seats_raw[raw_party] = seats_raw.get(raw_party, 0) + bold
    if not seats and not votes:
        return None
    return seats, seats_raw, votes


def main():
    regions_out: dict[str, dict] = {}
    misses: list[str] = []
    seat_totals: dict[int, int] = {y: 0 for y in TARGET_YEARS}
    gb_winners: dict[int, dict[str, int]] = {y: {} for y in TARGET_YEARS}

    for eer_code, name, wiki_title in EU_PARLIAMENT_REGIONS:
        path = SOURCE / f'wiki_ep_{eer_code}.json'
        if not path.exists():
            print(f'  WARN: {path.relative_to(ROOT)} not cached — '
                  f'run scripts/29 first.', file=sys.stderr)
            continue
        raw = json.loads(path.read_text())
        wt = raw.get('parse', {}).get('wikitext', '')
        url = wiki_url(wiki_title)

        history: list[dict] = []
        for year in TARGET_YEARS:
            block = extract_year_block(wt, year)
            if not block:
                misses.append(f'{eer_code} {name} {year}: no year block')
                continue
            parsed = parse_year_block(block)
            if not parsed:
                misses.append(f'{eer_code} {name} {year}: no candidate rows')
                continue
            seats, seats_raw, votes = parsed
            if not votes:
                misses.append(f'{eer_code} {name} {year}: no vote totals')
                continue
            plurality = max(sorted(votes), key=lambda p: votes[p])
            history.append({
                'y':         year,
                'w':         plurality,
                'src':       'wikipedia',
                'url':       url,
                'seats':     seats,
                'seats_raw': seats_raw,
                'votes':     votes,
            })
            seat_totals[year] += sum(seats.values())
            # Per-region seat-count by plurality winner (for the GB
            # by-year tally in the stderr summary).
            for p, n in seats.items():
                gb_winners[year][p] = gb_winners[year].get(p, 0) + n
            seat_summary = ' / '.join(
                f'{p} {n}' for p, n in sorted(seats.items(), key=lambda kv: -kv[1])
            )
            print(f'{eer_code} {name:30s} {year}  plurality={plurality:>12s}  '
                  f'seats: {seat_summary}')

        if history:
            regions_out[eer_code] = {
                'name':    name,
                'history': history,
            }

    DATA.mkdir(parents=True, exist_ok=True)
    out_data = {'years': list(TARGET_YEARS), 'regions': regions_out}
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, indent=2))

    print(f'\nWrote {OUT.relative_to(ROOT)} — {len(regions_out)}/'
          f'{len(EU_PARLIAMENT_REGIONS)} regions, '
          f'{sum(len(r["history"]) for r in regions_out.values())} region-years')
    for y in TARGET_YEARS:
        winners_summary = ' / '.join(
            f'{p} {n}' for p, n in sorted(gb_winners[y].items(), key=lambda kv: -kv[1])
        )
        print(f'  {y}: {seat_totals[y]:2d} GB seats — {winners_summary}')

    if misses:
        print(file=sys.stderr)
        for m in misses:
            print(f'  WARN: {m}', file=sys.stderr)


if __name__ == '__main__':
    main()
