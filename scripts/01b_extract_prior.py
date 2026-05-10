"""Parse cached Wikipedia wikitext into per-ward prior winners.

Reads data/source/wiki_<borough>_<year>.json (produced by 00) and writes
data/prior_winners.json:

    { borough: { ward_name: { prior_party, prior_year } } }

We use the **top-of-poll party** as "prior winner" — i.e. the first
`{{Election box winning candidate with party link...}}` template within each
ward's wikitext section. This works uniformly for:

- Thirds boroughs in 2022 where only one seat per ward was up (one winning
  candidate template per ward — that's the seat).
- All-out boroughs (Bury, Rochdale 2022 post-boundary; Salford 2021) where
  three winning candidates were elected per ward — Wikipedia lists them in
  vote-rank order, so the first template is top-of-poll.

This matches how the existing 2026 dataset records Salford winners (top of
poll), so the prior-vs-2026 comparison is apples-to-apples.

Wigan 2022 organises wards as h4 inside h3 constituency sections, so we collect
both heading levels.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"

# Articles fetched by 00 — kept aligned
SOURCES = [
    ('Bolton',     2022),
    ('Bury',       2022),
    ('Manchester', 2022),
    ('Oldham',     2022),
    ('Rochdale',   2022),
    ('Stockport',  2022),
    ('Tameside',   2022),
    ('Trafford',   2022),
    ('Wigan',      2022),
    ('Salford',    2021),
]

# Sections that come AFTER the ward-results block — anything past these is by-elections,
# changes-since, references, etc. We stop scanning for wards when we hit one of these h2s.
END_MARKERS = re.compile(
    r'^==\s*(?:By[- ]Elections?|Changes since|Aftermath|References|External links|Notes)\b[^=]*==\s*$',
    re.MULTILINE | re.IGNORECASE,
)

# Both h3 (===Ward===) and h4 (====Ward====) — Wigan uses h4 inside h3 constituency sections.
HEADING_RE = re.compile(r'^(={3,4})\s*([^=\n]+?)\s*\1\s*$', re.MULTILINE)

# Top-of-poll: first {{Election box winning candidate [with party link]... |party=PARTY...}}
# The "with party link" suffix is optional — minor parties (e.g. "Radcliffe First")
# without their own Wikipedia article use the link-less variant.
WINNER_RE = re.compile(
    r'\{\{Election box winning candidate(?:\s+with party link)?[^}]*?\|\s*party\s*=\s*([^|}\n]+)',
    re.IGNORECASE | re.DOTALL,
)
# Fallback: hold/gain template's winner= field (used for sections that only have a hold marker, no candidate row)
HOLDGAIN_RE = re.compile(
    r'\{\{Election box (?:hold|gain)[^|]*\|[^}]*?winner\s*=\s*([^|}\n]+)',
    re.IGNORECASE | re.DOTALL,
)


def normalize_party(raw: str) -> str:
    """Map Wikipedia party-name strings to the same labels the existing site uses."""
    s = raw.strip().lower().replace('[[', '').replace(']]', '')
    # Strip wikilinks like "Reform UK|Reform"
    if '|' in s:
        s = s.split('|', 1)[-1].strip()
    if 'labour' in s:
        return 'Labour'
    if 'conservative' in s:
        return 'Conservative'
    if 'liberal democrat' in s or 'lib dem' in s or s == 'libdem':
        return 'LibDem'
    if 'green' in s:
        return 'Green'
    if 'reform' in s:
        return 'Reform'
    if 'independent' in s:
        return 'Independent'
    # Local independent groupings — 2026 dataset classifies these as Independent,
    # so match that for the prior-vs-2026 comparison to be apples-to-apples.
    if s in {'radcliffe first', 'one kearsley', 'heald green ratepayers'}:
        return 'Independent'
    return 'Other'


def parse_article(borough: str, year: int, wt: str) -> dict:
    # Hard cap on where ward sections can live: stop at first end-marker h2.
    end_match = END_MARKERS.search(wt)
    ward_end = end_match.start() if end_match else len(wt)

    # Collect h3 + h4 headings that fall before the end marker.
    headings = [(m.start(), m.end(), m.group(2).strip())
                for m in HEADING_RE.finditer(wt) if m.end() < ward_end]

    out = {}
    for i, (h_start, h_end, name) in enumerate(headings):
        next_start = headings[i + 1][0] if i + 1 < len(headings) else ward_end
        section = wt[h_end:next_start]

        m = WINNER_RE.search(section) or HOLDGAIN_RE.search(section)
        if not m:
            continue  # not a ward section (History, constituency container, etc.)

        # Strip "ward" / "constituency" suffix common in Wigan's h4 names ("Atherton ward")
        clean = re.sub(r'\s+(ward|constituency)\s*$', '', name, flags=re.IGNORECASE).strip()
        if clean in out:
            continue  # duplicate heading; first occurrence wins
        out[clean] = {'prior_party': normalize_party(m.group(1)), 'prior_year': year}
    return out


def main():
    all_winners = {}
    summary_rows = []
    for borough, year in SOURCES:
        path = SOURCE / f'wiki_{borough.lower()}_{year}.json'
        with open(path) as f:
            wt = json.load(f)['parse']['wikitext']
        winners = parse_article(borough, year, wt)
        all_winners[borough] = winners
        # Per-borough party counts for sanity-checking
        counts = {}
        for w in winners.values():
            counts[w['prior_party']] = counts.get(w['prior_party'], 0) + 1
        summary_rows.append((borough, year, len(winners), counts))

    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / 'prior_winners.json', 'w') as f:
        json.dump(all_winners, f, indent=2)

    print(f'Saved prior_winners.json — {sum(len(v) for v in all_winners.values())} wards across {len(all_winners)} boroughs\n')
    for borough, year, n, counts in summary_rows:
        print(f'  {borough:>12} ({year}): {n:>2} wards | {counts}')


if __name__ == '__main__':
    main()
