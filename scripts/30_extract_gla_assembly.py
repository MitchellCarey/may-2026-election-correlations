"""Parse the four cached per-year London Assembly Wikipedia articles
(2012 / 2016 / 2021 / 2024) fetched by scripts/29 and emit one record per
(constituency, year) for FPTP winners plus one record per (London-wide,
year) for the list seat allocation (issue #89).

Wikipedia structure per year:

  - Each article carries a "Constituency candidates" wikitable with 14
    rows (one per LAC24 constituency). Within each row the winner's
    cell is bolded (`'''<name>'''`) and styled with a literal
    background-colour hex code. Column position varies by year; the
    background colour is what survives across years. Colour map:
        #faa / #ffaaaa             → Labour
        #aacfff                    → Conservative
        #ffd152                    → Liberal Democrats
    No constituency has ever been won by Green / UKIP / Reform; if a
    future contest does, the parser surfaces an `unknown bg=<colour>`
    WARN to stderr so the colour map can be extended.

  - Each article carries one of two summary templates with the
    London-wide list seat allocation per party:
        - 2016 / 2021 / 2024: `{{Election results}}` template, with
          per-party fields `partyN = [[Wiki|Label]]` + `seatsN_2 = N`
          (the `_2` suffix is the "second round" = list vote).
        - 2012: older `{{AMS Election Summary Party}}` per-party
          template, with `party = <name>` + `AMS seats = N`.
    Both shapes are handled and dispatched by article-content sniff.

Output: data/gla_assembly_raw.json — flat list of records, mixed by kind:
  # kind="fptp" — constituency winners
  {"lac24cd": "E32000001", "name": "Barnet and Camden",
   "year": 2024, "winner": "Labour", "candidate": "Anne Clarke",
   "url": "https://en.wikipedia.org/wiki/2024_London_Assembly_election",
   "kind": "fptp"}
  # kind="list" — London-wide list seat allocations
  {"region": "Greater London", "year": 2024,
   "seats": {"Labour": 1, "Conservative": 5, "Green": 3, "LibDem": 1, "Reform": 1},
   "seats_raw": {"Labour": 1, "Conservative": 5, "Green": 3, "Liberal Democrats": 1, "Reform UK": 1},
   "url": "https://en.wikipedia.org/wiki/2024_London_Assembly_election",
   "kind": "list"}

Coverage target: 14/14 constituencies × 4 years = 56 fptp records;
1 region × 4 years = 4 list records (each summing to 11 list seats).
Misses are surfaced to stderr per the "WARN on silent join failures" rule.
"""
import argparse
import json
import re
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gla_assembly import (
    GLA_ASSEMBLY_CONSTITUENCIES,
    GLA_ASSEMBLY_YEARS,
    GLA_ASSEMBLY_REGION_NAME,
    GLA_ASSEMBLY_LIST_SEATS,
)
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "gla_assembly_raw.json"


# Bolded winner cell background colours observed across 2012-2024. Keys
# are lowercased without the leading '#'. New colours (e.g. a future
# Green / Reform constituency win) surface as `unknown bg=` WARNs.
COLOUR_TO_PARTY = {
    'faa':     'Labour',
    'ffaaaa':  'Labour',
    'aacfff':  'Conservative',
    'ffd152':  'LibDem',
    # Defensive — not observed in 2012-2024 but trivially adding for the
    # most likely future cases. Standard "light" tints used by the
    # London Assembly article editors.
    'd6f3d6':  'Green',
    'b3e0ff':  'Reform',
    'ffcca8':  'LibDem',  # alternative orange tint
}


def wikipedia_url(title: str) -> str:
    return f'https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(" ", "_"), safe="_,()/")}'


def cache_path(year: int) -> Path:
    return SOURCE / f'wiki_gla_assembly_{year}.json'


# Match a constituency-row bold winner cell. The row is anchored on the
# `[[<Name> (London Assembly constituency)|...]]` link; we then capture the
# next cell (one of the per-party columns) that contains a bolded name with
# a `style="background:<colour>"` declaration. The bold marker is `'''…'''`.
#
# Whitespace between the row marker and the wikilink, between the style
# attribute and the pipe, and between cells, is loose across years.
ROW_OPEN_TEMPLATE = (
    r'\|\s*\[\[\s*{name_pattern}\s*\(London Assembly constituency\)[^\]]*\]\]'
)

# Match a single cell with bolded winner + style background. The bolded
# block looks like `'''<name>'''` where `<name>` may be a wikilink
# (`[[Target|Display]]` or `[[Plain]]`) and may carry `{{efn|...}}`
# annotations between the closing `]]` and the closing `'''`. We capture
# the whole bold body and let _strip_winner_name reduce it to a clean
# display name. Single apostrophes in winner surnames (e.g. O'Connell)
# don't terminate the match because the closer is literally three quotes.
WINNER_CELL_RE = re.compile(
    r'\|\s*style\s*=\s*"[^"]*?background\s*:\s*\#?([0-9a-fA-F]{3,8})[^"]*"\s*'
    r"\|\s*'''(.+?)'''",
    re.DOTALL,
)


def _strip_winner_name(bold_body: str) -> str:
    """Reduce the bold body to a clean display name. Handles:
        [[Page Title]]               → "Page Title"
        [[Page Title|Display Name]]  → "Display Name"
        [[Page Title]] (I)           → "Page Title"
        [[Page Title]]{{efn|...}}    → "Page Title"
        Plain Name                   → "Plain Name"
    Trailing `(I)` incumbency markers and `{{efn|...}}` notes are
    stripped so the candidate field is clean for tooltip use.
    """
    text = bold_body
    # Resolve wikilinks (prefer display label when piped).
    text = re.sub(
        r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]',
        lambda m: m.group(2) or m.group(1),
        text,
    )
    # Drop `{{efn|...}}` and similar single-template annotations.
    text = re.sub(r'\{\{[^{}]*\}\}', '', text)
    # Drop trailing `(I)` / `(I.)` etc — incumbency notation.
    text = re.sub(r'\s*\(I\.?\)\s*$', '', text)
    # Collapse HTML entities — Wikipedia editors sometimes use `&nbsp;`
    # inside display labels (Andrew&nbsp;Dismore, 2012) which leaks
    # through the wikilink resolver as a literal substring.
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    return ' '.join(text.split())


def find_constituency_row(text: str, name: str) -> str | None:
    """Find the table row for the given constituency display name. Returns
    the row text (from the constituency-name link to the next row separator
    `|-` or table close `|}`), or None if absent."""
    # Build a tolerant pattern allowing en-dash / ampersand / spaces in
    # display name. The link target uses the canonical name; the display
    # piped after `|` may abbreviate (e.g. "Barnet & Camden").
    name_re = re.escape(name)
    open_re = re.compile(
        rf'\|\s*\[\[\s*{name_re}\s*\(London Assembly constituency\)[^\]]*\]\]'
    )
    m = open_re.search(text)
    if not m:
        return None
    start = m.start()
    # Stop at the next row separator or table end.
    tail = text[m.end():]
    stop = re.search(r'\n\|-|\n\|\}', tail)
    end = m.end() + (stop.start() if stop else len(tail))
    return text[start:end]


def parse_fptp_winner(row_text: str) -> tuple[str, str] | None:
    """Return (winner_party, winner_name) or None if not parseable."""
    m = WINNER_CELL_RE.search(row_text)
    if not m:
        return None
    bg = m.group(1).lower()
    name = _strip_winner_name(m.group(2))
    party = COLOUR_TO_PARTY.get(bg)
    if not party:
        print(f'  WARN: unknown bg colour #{bg} in row: {row_text[:120]!r}',
              file=sys.stderr)
        return None
    return party, name


# {{Election results}} per-party field block. We pull `partyN = ...` and
# `seatsN_2 = ...` pairs. Field values may contain `|` inside wikilinks
# (`[[Labour Party (UK)|Labour]]`) — the body uses `||` or `\n|` as the
# inter-field separator. PARTY_FIELD_RE captures the whole link-bearing
# value up to (but not including) the next `||` / `\n|` / `}}`; the
# wikilink resolver then reduces it to a clean display label.
ELECTION_RESULTS_OPEN_RE = re.compile(
    r'\{\{\s*Election\s+results\b',
    re.IGNORECASE,
)
PARTY_FIELD_RE = re.compile(
    r'\|\s*party(\d+)\s*=\s*(.+?)(?=\|\||\n\s*\||\}\})',
    re.IGNORECASE | re.DOTALL,
)
SEATS2_FIELD_RE = re.compile(
    r'\|\s*seats(\d+)_2\s*=\s*(\d+)',
    re.IGNORECASE,
)


def extract_template_body(text: str, open_re: re.Pattern) -> str | None:
    """Return the body of the first template whose opening matches
    `open_re`, scanning brace-balanced to handle nested `{{…}}` templates
    inside the body."""
    m = open_re.search(text)
    if not m:
        return None
    i = m.start() + 2  # past the `{{`
    depth = 1
    while i < len(text):
        if text[i:i+2] == '{{':
            depth += 1
            i += 2
        elif text[i:i+2] == '}}':
            depth -= 1
            if depth == 0:
                return text[m.start()+2:i]
            i += 2
        else:
            i += 1
    return None


def parse_list_seats_election_results(text: str) -> tuple[dict[str, int], dict[str, int]] | None:
    """Parse the `{{Election results}}` template (2016 / 2021 / 2024) for
    the London-wide list seat allocation. Returns (seats_normalised,
    seats_raw) or None if the template is absent."""
    body = extract_template_body(text, ELECTION_RESULTS_OPEN_RE)
    if body is None:
        return None
    # Map party-N → raw label, and party-N → seats_2.
    party_by_n: dict[str, str] = {}
    seats_by_n: dict[str, int] = {}
    for m in PARTY_FIELD_RE.finditer(body):
        party_by_n[m.group(1)] = m.group(2).strip()
    for m in SEATS2_FIELD_RE.finditer(body):
        try:
            seats_by_n[m.group(1)] = int(m.group(2))
        except ValueError:
            continue
    seats_norm: dict[str, int] = defaultdict(int)
    seats_raw: dict[str, int] = defaultdict(int)
    for n, seats in seats_by_n.items():
        if seats == 0:
            continue
        raw_label = party_by_n.get(n, '')
        if not raw_label:
            continue
        # Strip `[[Link|Label]]` to "Label"; strip `[[Plain]]` to "Plain".
        # PARTY_FIELD_RE may capture trailing junk for templates that use a
        # single-pipe field separator (2024 article); the wikilink anchor
        # at the start of the field is the canonical label, so we resolve
        # that first and discard the tail.
        link_m = re.match(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', raw_label)
        display = (link_m.group(2) or link_m.group(1)) if link_m else raw_label
        display = display.strip()
        seats_raw[display] += seats
        seats_norm[normalize_party(display)] += seats
    return dict(seats_norm), dict(seats_raw)


# {{AMS Election Summary Party}} per-party template (2012). Each block
# carries `|party = X` + `|AMS seats = N`. Multiple templates appear in the
# Results section, one per party.
AMS_SUMMARY_BLOCK_RE = re.compile(
    r'\{\{\s*AMS\s+Election\s+Summary\s+Party\b'
    r'((?:[^{}]|\{\{[^{}]*\}\})*?)'
    r'\}\}',
    re.IGNORECASE | re.DOTALL,
)
AMS_PARTY_RE = re.compile(r'\|\s*party\s*=\s*([^\n|]+)', re.IGNORECASE)
AMS_SEATS_RE = re.compile(r'\|\s*AMS\s+seats\s*=\s*(\d+)', re.IGNORECASE)


def parse_list_seats_ams_summary(text: str) -> tuple[dict[str, int], dict[str, int]] | None:
    """Parse `{{AMS Election Summary Party}}` blocks (2012 fallback).
    Returns (seats_normalised, seats_raw) or None if absent."""
    blocks = list(AMS_SUMMARY_BLOCK_RE.finditer(text))
    if not blocks:
        return None
    seats_norm: dict[str, int] = defaultdict(int)
    seats_raw: dict[str, int] = defaultdict(int)
    for b in blocks:
        body = b.group(1)
        pm = AMS_PARTY_RE.search(body)
        sm = AMS_SEATS_RE.search(body)
        if not pm or not sm:
            continue
        raw_label = pm.group(1).strip()
        try:
            seats = int(sm.group(1))
        except ValueError:
            continue
        if seats == 0:
            continue
        link_m = re.match(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', raw_label)
        display = (link_m.group(2) or link_m.group(1)) if link_m else raw_label
        display = display.strip()
        seats_raw[display] += seats
        seats_norm[normalize_party(display)] += seats
    return dict(seats_norm), dict(seats_raw)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.parse_args()

    records: list[dict] = []
    fptp_counts: dict[int, int] = defaultdict(int)
    list_counts: dict[int, int] = defaultdict(int)

    for year, title in GLA_ASSEMBLY_YEARS:
        path = cache_path(year)
        if not path.exists():
            print(f'  ! missing cache for {year}: {path.relative_to(ROOT)} — '
                  f'run scripts/29 first.', file=sys.stderr)
            continue
        data = json.loads(path.read_text())
        text = data.get('parse', {}).get('wikitext', '')
        if not text:
            print(f'  ! empty wikitext for {year}', file=sys.stderr)
            continue
        url = wikipedia_url(title)

        # --- FPTP per-constituency winners ---
        for lac24cd, name in GLA_ASSEMBLY_CONSTITUENCIES:
            row = find_constituency_row(text, name)
            if row is None:
                print(f'  WARN: no row for {lac24cd} ({name}) in {year}',
                      file=sys.stderr)
                continue
            parsed = parse_fptp_winner(row)
            if parsed is None:
                print(f'  WARN: no parseable winner for {lac24cd} ({name}) in {year}',
                      file=sys.stderr)
                continue
            party, candidate = parsed
            records.append({
                'lac24cd':   lac24cd,
                'name':      name,
                'year':      year,
                'winner':    party,
                'candidate': candidate,
                'url':       url,
                'kind':      'fptp',
            })
            fptp_counts[year] += 1

        # --- London-wide list seat allocation ---
        seats = parse_list_seats_election_results(text)
        if seats is None:
            seats = parse_list_seats_ams_summary(text)
        if seats is None:
            print(f'  WARN: no list-seat template found for {year}',
                  file=sys.stderr)
            continue
        seats_norm, seats_raw = seats
        total_list = sum(seats_norm.values())
        if total_list != GLA_ASSEMBLY_LIST_SEATS:
            print(f'  WARN: list seats sum to {total_list} (expected '
                  f'{GLA_ASSEMBLY_LIST_SEATS}) for {year} — '
                  f'seats={dict(seats_norm)}',
                  file=sys.stderr)
        records.append({
            'region':     GLA_ASSEMBLY_REGION_NAME,
            'year':       year,
            'seats':      seats_norm,
            'seats_raw':  seats_raw,
            'url':        url,
            'kind':       'list',
        })
        list_counts[year] += 1

    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2))

    n_fptp = sum(fptp_counts.values())
    n_list = sum(list_counts.values())
    print(f'Wrote {OUT.relative_to(ROOT)} — {n_fptp} FPTP records '
          f'({len(GLA_ASSEMBLY_CONSTITUENCIES) * len(GLA_ASSEMBLY_YEARS)} expected), '
          f'{n_list} list records ({len(GLA_ASSEMBLY_YEARS)} expected)')
    for year, _ in GLA_ASSEMBLY_YEARS:
        print(f'  {year}: fptp {fptp_counts[year]}/14 · '
              f'list {list_counts[year]}/1')


if __name__ == '__main__':
    main()
