"""Parse the 73 cached per-constituency + 8 cached per-region Wikipedia
articles fetched by scripts/17b_fetch_holyrood_history.py and emit one
record per (constituency, year) plus one per (region, year) for the
2016 and 2021 Scottish Parliament elections.

**Constituency winners (kind="fptp")** — per-constituency articles use
the **AMS election box** template family (Additional Member System —
Holyrood's hybrid FPTP-plus-regional-list voting):

  {{AMS election box begin |title=[[YYYY Scottish Parliament election]]: <Name>...}}
  {{AMS election box with party link
    |party     = Scottish National Party
    |candidate = [[Kevin Stewart...]]
    |votes     = 10,058
    |winner    = yes
  }}
  ... other candidates without winner=yes ...
  {{AMS election box turnout ...}}
  {{AMS election box win|winner = SNP}}   OR   {{AMS election box hold|winner=...}}
  {{AMS election box end|notes=yes}}

The parser walks each `AMS election box begin ... end` block, captures the
year from the title, and extracts the winner by:
  1. preferring the candidate row marked `|winner = yes`
  2. falling back to the `AMS election box {win,hold,gain}` template's
     `winner = ...` parameter

**Regional list seats (kind="regional")** — per-region articles carry one
section per contest year (`===YYYY Scottish Parliament election===` or
the shorter `===YYYY election===` Highlands and Islands uses) containing
the regional-list seat winners in one of two on-wiki layouts:

  Variant A (post-2016 articles + Glasgow/NES/West 2016):
    {{Election box begin for list|title=[[YYYY Scottish Parliament election]]: <Region>...}}
    {{Election box candidate with party link
      |party     = Scottish Labour
      |candidate = '''[[Pauline McNeill]]''', '''[[Anas Sarwar]]''', plain, ''[[italic]]''
      |number    = 4              ← optional; older articles omit it
      |votes     = 74,088
    }}
    ... one row per party in the region's regional vote ballot ...
    {{Election box end}}

  Variant B (pre-2021 articles for Central / Lothian / Mid&Fife / South):
    {| class=wikitable
    ! Party !! Elected candidates !! Seats !! ...
    |-
    {{Election box scottish candidate electoral region with party link
      |party    = Scottish Conservatives
      |number   = 3                    ← always present
      |elected  = [[Miles Briggs]]<br />[[Gordon Lindhurst]]<br />[[Jeremy Balfour]]
    }}
    ... one row per party ...
    {{Election box end}}

We prefer the explicit `|number = N` parameter when present (Variant B
always, some Variant A rows); fall back to counting `'''bold'''` markers
in the candidate field (Variant A older rows). Bold markup `'''Name'''`
is the on-wiki convention for "this list candidate was elected", italic
markup `''Name''` for "elected via the constituency vote, also on the
list" (don't count toward list seats).

The kind discriminator lets 04f split FPTP vs regional list records
downstream. Output: data/holyrood_history_raw.json — flat list of records:

  # kind="fptp"
  {"spc22cd": "S16000074", "name": "Aberdeen Central",
   "year": 2021, "winner": "SNP", "candidate": "Kevin Stewart",
   "source": "wiki", "url": "https://en.wikipedia.org/wiki/...",
   "kind": "fptp"}
  # kind="regional"
  {"region": "Glasgow", "year": 2021,
   "seats":     {"Labour": 4, "Conservative": 2, "Green": 1},
   "seats_raw": {"Scottish Labour": 4, "Scottish Conservatives": 2,
                 "Scottish Greens": 1},
   "source": "wiki", "url": "https://en.wikipedia.org/wiki/...",
   "kind": "regional"}

Coverage targets:
  Constituencies: 73/73 at 2016 + 2021 (same as Phase 1C baseline).
  Regions: 8 × 2 = 16 region-years × 7 list seats per region = 112 list
    seats. (REGIONAL_TARGET_YEARS = 2016 + 2021 only — pre-review polygons
    in 07d's slider only paint at year < 2026, and the 8 pre-review
    regions are abolished/redistricted by the 2026 boundary review, so
    2026 data for the SPC22-era regions is moot semantically.)
"""
import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _holyrood_constituencies import HOLYROOD_22, HOLYROOD_REGIONS_22
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "holyrood_history_raw.json"

TARGET_YEARS = (2016, 2021)
# Regional list extraction is pre-review-only. Pre-review polygons only
# paint at year < 2026 in 07d's slider; the SPC22-era 8 regions are
# replaced by a redrawn region map at the 2026 boundary review. Including
# 2026 here would only matter if a future change wired regional-list
# tooltip lines onto post-era (SPC26) polygons — out of scope for #83.
REGIONAL_TARGET_YEARS = (2016, 2021)

# === Constituency block matching ===

# Match the opening of an AMS election box block; capture position only.
# (Some articles use plain `{{Election box begin}}` for pre-2007 contests —
# we don't need those for Phase 1C, so we filter on AMS only.)
AMS_BEGIN_RE = re.compile(r'\{\{\s*AMS\s+election\s+box\s+begin\b', re.IGNORECASE)
AMS_END_RE = re.compile(r'\{\{\s*AMS\s+election\s+box\s+end[^}]*\}\}', re.IGNORECASE)

# Year captured from `title = [[YYYY Scottish Parliament election]]: ...`.
TITLE_YEAR_RE = re.compile(
    r'title\s*=\s*\[\[\s*(\d{4})\s+Scottish\s+Parliament\s+election',
    re.IGNORECASE,
)

# Opening marker for a candidate row — body extraction below is brace-aware
# because rows contain nested templates like `{{increase}}1.7` whose `}}`
# would otherwise terminate a naive `(.*?)\}\}` match prematurely.
CANDIDATE_OPEN_RE = re.compile(
    r'\{\{\s*AMS\s+election\s+box\s+with(?:\s+list)?\s+party\s+link\b',
    re.IGNORECASE,
)


def iter_candidate_bodies(block_text, open_re=CANDIDATE_OPEN_RE):
    """Yield the body of each candidate-row template in `block_text`,
    scanning brace-balanced so nested `{{increase}}` etc. don't truncate
    the row. Body excludes the opening template name. Default `open_re`
    matches `AMS election box with [list] party link`; pass a different
    regex for the regional-list templates."""
    for m in open_re.finditer(block_text):
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

# The value captures consume either a complete `[[...]]` wikilink (so the
# internal `|` of disambiguated forms like `[[Kevin Stewart (Scottish
# politician)|Kevin Stewart]]` doesn't truncate the value) or a single
# non-terminating character. Without the wikilink alternation the capture
# stops at the first `|` and `clean_candidate`'s `[[Foo|Bar]]` cleanup
# regex (which requires the closing `]]`) leaves the broken link verbatim.
PARTY_PARAM_RE  = re.compile(
    r'\|\s*party\s*=\s*((?:\[\[[^\]]*\]\]|[^\n|}])+)',
    re.IGNORECASE,
)
CANDIDATE_PARAM_RE = re.compile(
    r'\|\s*candidate\s*=\s*((?:\[\[[^\]]*\]\]|[^\n|}])+)',
    re.IGNORECASE,
)
WINNER_PARAM_RE = re.compile(r'\|\s*winner\s*=\s*yes\b', re.IGNORECASE)

# Tail templates that record the win for AMS-formatted articles.
TAIL_WIN_RE = re.compile(
    r'\{\{\s*AMS\s+election\s+box\s+(?:win|hold|gain)\b[^}]*?\|\s*winner\s*=\s*([^\n|}]+)',
    re.IGNORECASE | re.DOTALL,
)


def clean_candidate(raw: str) -> str:
    """Strip wikilink wrapping from a `candidate = ...` value, preferring
    the display label of a piped wikilink (`[[Title|Display]]` → `Display`)
    over the title. A bare wikilink with a parenthesised disambiguator
    (`[[Foo (politician)]]`) keeps the disambiguator — today's dataset
    has zero such candidates, so stripping it hasn't been worthwhile.
    Tolerant of trailing refs/HTML noise."""
    s = raw.strip()
    s = re.sub(r'<ref.*?(?:/>|</ref>)', '', s, flags=re.DOTALL)
    # [[Foo|Bar]] → Bar; [[Foo]] → Foo
    m = re.search(r'\[\[([^\]\|]+?)(?:\|([^\]]+))?\]\]', s)
    if m:
        s = (m.group(2) or m.group(1)).strip()
    s = re.sub(r"'''", '', s)
    return s.strip(" '")


def clean_party(raw: str) -> str:
    """Strip wikilink wrapping and stray whitespace from a `party = ...`
    value. Mirrors clean_candidate but doesn't strip bold markup (party
    names aren't bolded in the on-wiki templates we parse)."""
    s = raw.strip()
    m = re.match(r'\[\[([^\]\|]+?)(?:\|([^\]]+))?\]\]', s)
    if m:
        s = (m.group(2) or m.group(1)).strip()
    return s.strip(" '")


def find_blocks(wt: str) -> list[tuple[int, int]]:
    """Return (start, end) spans for every AMS election box block. The end
    is the position *after* the closing `{{AMS election box end...}}`."""
    spans = []
    for begin in AMS_BEGIN_RE.finditer(wt):
        end_m = AMS_END_RE.search(wt, begin.end())
        if not end_m:
            continue
        spans.append((begin.start(), end_m.end()))
    return spans


def extract_winner(block_text: str) -> tuple[str | None, str | None]:
    """Walk a single AMS block and return (party_raw, candidate_raw) for the
    winner, or (None, None) if not found. Tries the row-level `winner=yes`
    marker first, then the tail `AMS election box {win,hold,gain}` template."""
    for body in iter_candidate_bodies(block_text):
        if not WINNER_PARAM_RE.search(body):
            continue
        pm = PARTY_PARAM_RE.search(body)
        cm = CANDIDATE_PARAM_RE.search(body)
        if pm:
            return pm.group(1).strip(), clean_candidate(cm.group(1)) if cm else None

    # Fallback: tail template carries `winner=<party>`.
    tail = TAIL_WIN_RE.search(block_text)
    if tail:
        return tail.group(1).strip(), None

    return None, None


def wiki_url(title: str) -> str:
    """Same convention as 04d / 04e."""
    return f'https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(" ", "_"), safe="_,()/")}'


# === Regional-list block matching ===

# Each year's regional-list section header. Two observed forms:
#   ===YYYY Scottish Parliament election===
#   ===YYYY election===                (Highlands and Islands shorthand)
# Accepts both. Year captured.
YEAR_SECTION_RE = re.compile(
    r'^=+\s*(\d{4})(?:\s+Scottish\s+Parliament)?\s+election\s*=+\s*$',
    re.MULTILINE | re.IGNORECASE,
)

# Variant A opening: candidate row inside `{{Election box begin for list}}`.
# Two on-wiki names observed: `Election box candidate with party link`
# (most rows; one row per party) and bare `Election box candidate` (used
# for parties without a Wikipedia article, e.g. Freedom Alliance).
LIST_CANDIDATE_OPEN_RE = re.compile(
    r'\{\{\s*Election\s+box\s+candidate(?:\s+with\s+(?:list\s+)?party\s+link)?\b',
    re.IGNORECASE,
)
# Variant B opening: candidate row inside a level-4 wikitable, used by
# the 2016 Central/Lothian/Mid&Fife/South region articles. Different
# template name. The `number = N` field is always populated here.
LIST_CANDIDATE_OPEN_B_RE = re.compile(
    r'\{\{\s*Election\s+box\s+scottish\s+candidate\s+electoral\s+region'
    r'(?:\s+with\s+party\s+link)?\b',
    re.IGNORECASE,
)
# Combined opener matching either variant. Order of alternation doesn't
# matter — `iter_candidate_bodies` only uses `.end()` to start its
# brace-balanced walk.
LIST_CANDIDATE_OPEN_ANY_RE = re.compile(
    LIST_CANDIDATE_OPEN_B_RE.pattern + '|' + LIST_CANDIDATE_OPEN_RE.pattern,
    re.IGNORECASE,
)

# `|number = N` — Variant B always populates this; some Variant A rows do too.
# Prefer this when present (most reliable seat-count signal).
NUMBER_PARAM_RE = re.compile(
    r'\|\s*number\s*=\s*(\d+)\b',
    re.IGNORECASE,
)

# Bold-name boundary: exactly 3 single quotes, not preceded or followed by
# another `'`. Each `'''Name'''` bold span has 2 boundaries; n_seats = n // 2.
# Italic markup `''Name''` (2 quotes) doesn't match — that's the on-wiki
# convention for "elected via the constituency vote, not the list".
BOLD_BOUNDARY_RE = re.compile(r"(?<!')'''(?!')")


def parse_regional_list(wt: str, region_name: str, region_url: str) -> list[dict]:
    """Walk a per-region article's wikitext and yield one record per
    (region, year) in REGIONAL_TARGET_YEARS containing both a `seats`
    (normalised party → seat count) dict and a `seats_raw` dict (raw
    Wikipedia party strings — e.g. "Scottish Labour", "Alba Party" —
    preserved so tooltips can render historical accuracy where the
    normaliser flattens minor parties to "Other")."""
    records: list[dict] = []
    headers = [(m.start(), m.end(), int(m.group(1)))
               for m in YEAR_SECTION_RE.finditer(wt)]
    # Headers are emitted in document order. Sort by start to be safe.
    headers.sort()
    for i, (_hs, he, year) in enumerate(headers):
        if year not in REGIONAL_TARGET_YEARS:
            continue
        # Body extends to the start of the next year section (regardless
        # of the next year). Sub-sections (==== Constituency results ====
        # / ==== Additional member results ====) live INSIDE this body.
        next_start = headers[i + 1][0] if i + 1 < len(headers) else len(wt)
        body = wt[he:next_start]
        seats: dict[str, int] = {}
        seats_raw: dict[str, int] = {}
        for cand_body in iter_candidate_bodies(body, open_re=LIST_CANDIDATE_OPEN_ANY_RE):
            pm = PARTY_PARAM_RE.search(cand_body)
            if not pm:
                continue
            raw_party = clean_party(pm.group(1))
            if not raw_party:
                continue
            # Prefer the explicit `|number = N` parameter; fall back to
            # counting `'''bold'''` markers in the candidate field for
            # older Variant A rows that omit `number`.
            nm = NUMBER_PARAM_RE.search(cand_body)
            if nm:
                n_seats = int(nm.group(1))
            else:
                cm = CANDIDATE_PARAM_RE.search(cand_body)
                if not cm:
                    continue
                # Note: CANDIDATE_PARAM_RE stops at the first \n, so multi-
                # line candidate fields would undercount. The on-wiki rows
                # we see keep the candidate field on a single (often long)
                # line, so this is safe in practice. If a future article
                # wraps candidate names across lines, the `number = N`
                # path is the reliable fallback.
                boundaries = len(BOLD_BOUNDARY_RE.findall(cm.group(1)))
                n_seats = boundaries // 2
            if n_seats <= 0:
                continue
            normalised = normalize_party(raw_party)
            seats[normalised] = seats.get(normalised, 0) + n_seats
            seats_raw[raw_party] = seats_raw.get(raw_party, 0) + n_seats
        if not seats:
            continue
        records.append({
            'region':    region_name,
            'year':      year,
            'seats':     seats,
            'seats_raw': seats_raw,
            'source':    'wiki',
            'url':       region_url,
            'kind':      'regional',
        })
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.parse_args()

    records: list[dict] = []
    misses_by_year: dict[int, list[str]] = {y: [] for y in TARGET_YEARS}
    matches_by_year: dict[int, int] = {y: 0 for y in TARGET_YEARS}

    # Pass 1: per-constituency FPTP winners.
    for spc22cd, name, _region, wiki_title in HOLYROOD_22:
        path = SOURCE / f'wiki_holyrood_constituency_{spc22cd}.json'
        if not path.exists():
            print(f'  WARN: {path.relative_to(ROOT)} not cached — '
                  f'run scripts/17b first.', file=sys.stderr)
            continue
        raw = json.loads(path.read_text())
        wt = raw.get('parse', {}).get('wikitext', '')
        url = wiki_url(wiki_title)

        # Index AMS blocks by year so each TARGET_YEARS lookup is O(1).
        blocks_by_year: dict[int, str] = {}
        for s, e in find_blocks(wt):
            block_text = wt[s:e]
            ym = TITLE_YEAR_RE.search(block_text[:600])  # title is in the leading template
            if not ym:
                continue
            year = int(ym.group(1))
            blocks_by_year.setdefault(year, block_text)  # first-write-wins per year

        for year in TARGET_YEARS:
            block = blocks_by_year.get(year)
            if not block:
                misses_by_year[year].append(f'{spc22cd} · {name}')
                continue
            party_raw, candidate = extract_winner(block)
            if not party_raw:
                misses_by_year[year].append(f'{spc22cd} · {name} (no winner row)')
                continue
            party = normalize_party(party_raw)
            records.append({
                'spc22cd':   spc22cd,
                'name':      name,
                'year':      year,
                'winner':    party,
                'candidate': candidate,
                'source':    'wiki',
                'url':       url,
                'kind':      'fptp',
            })
            matches_by_year[year] += 1

    # Pass 2: per-region regional-list seat allocations.
    regional_misses_by_year: dict[int, list[str]] = {y: [] for y in REGIONAL_TARGET_YEARS}
    regional_matches_by_year: dict[int, int] = {y: 0 for y in REGIONAL_TARGET_YEARS}
    regional_seat_totals: dict[int, int] = {y: 0 for y in REGIONAL_TARGET_YEARS}
    for region_name, region_wiki_title in HOLYROOD_REGIONS_22:
        slug = region_name.lower().replace(' ', '_')
        path = SOURCE / f'wiki_holyrood_region_{slug}.json'
        if not path.exists():
            print(f'  WARN: {path.relative_to(ROOT)} not cached — '
                  f'run scripts/17b first.', file=sys.stderr)
            continue
        raw = json.loads(path.read_text())
        wt = raw.get('parse', {}).get('wikitext', '')
        url = wiki_url(region_wiki_title)
        region_recs = parse_regional_list(wt, region_name, url)
        seen_years = {r['year'] for r in region_recs}
        for r in region_recs:
            records.append(r)
            regional_matches_by_year[r['year']] += 1
            regional_seat_totals[r['year']] += sum(r['seats'].values())
        for y in REGIONAL_TARGET_YEARS:
            if y not in seen_years:
                regional_misses_by_year[y].append(region_name)

    # Sort: fptp first (by year, code), then regional (by year, region).
    def sort_key(r):
        if r.get('kind') == 'fptp':
            return (0, r['year'], r['spc22cd'])
        return (1, r['year'], r['region'])
    records.sort(key=sort_key)
    OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False))

    n_const = len(HOLYROOD_22)
    n_reg = len(HOLYROOD_REGIONS_22)
    n_fptp = sum(1 for r in records if r.get('kind') == 'fptp')
    n_regional = sum(1 for r in records if r.get('kind') == 'regional')
    print(f'\nWrote {OUT.relative_to(ROOT)}: {len(records)} records '
          f'({n_fptp} fptp + {n_regional} regional)')
    print('  Constituency winners (kind=fptp):')
    for y in TARGET_YEARS:
        ok = matches_by_year[y]
        miss = len(misses_by_year[y])
        print(f'    {y}: {ok}/{n_const} matched · {miss} unmatched')
    print('  Regional list seats (kind=regional):')
    for y in REGIONAL_TARGET_YEARS:
        ok = regional_matches_by_year[y]
        miss = len(regional_misses_by_year[y])
        seat_total = regional_seat_totals[y]
        # 8 regions × 7 list seats = 56 list seats per year.
        print(f'    {y}: {ok}/{n_reg} regions matched · '
              f'{seat_total}/56 list seats · {miss} unmatched')

    for y in TARGET_YEARS:
        if misses_by_year[y]:
            print(f'\n  WARN: {y} constituencies unmatched '
                  f'({len(misses_by_year[y])}):', file=sys.stderr)
            for m in misses_by_year[y]:
                print(f'    {m}', file=sys.stderr)
    for y in REGIONAL_TARGET_YEARS:
        if regional_misses_by_year[y]:
            print(f'\n  WARN: {y} regions unmatched '
                  f'({len(regional_misses_by_year[y])}):', file=sys.stderr)
            for m in regional_misses_by_year[y]:
                print(f'    {m}', file=sys.stderr)


if __name__ == '__main__':
    main()
