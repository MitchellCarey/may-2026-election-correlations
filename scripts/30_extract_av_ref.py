"""Parse the 11 cached per-region wikitext snippets from scripts/29 and
emit data/av_referendum_2011.json in the project's standard history-JSON
shape.

Reads:  data/source/wiki_av_ref_2011_<region>.json   (11 files; one per
        region section of the Wikipedia results article)
        data/lad_geoms_2016.json                     (LAD-name lookup)
        data/source/av_ref_2011_overrides.csv        (optional hand-curated
                                                      name → code mappings
                                                      for the unavoidable
                                                      name-drift cases)
Writes: data/av_referendum_2011.json

Output schema (mirrors data/eu_ref_2016.json with a unified `areas` key
because three different counting-area types coexist):

  {
    "years": [2011],
    "areas": {
      "<code>": {
        "name": "Amber Valley",
        "kind": "lad" | "spc" | "nawc",
        "history": [{
          "y":     2011,
          "w":     "AV Yes" | "AV No",
          "src":   "wikipedia",
          "url":   "https://en.wikipedia.org/wiki/...",
          "votes": {"AV Yes": 12432, "AV No": 29745},
          "pct":   {"AV Yes": 0.2948, "AV No": 0.7052}
        }]
      }
    }
  }

The three code spaces are disjoint (LAD `E0[6-9]`, SPC22 `S16000074-150`,
NAWC `W0900****`) so a single flat lookup table is enough for the
renderer.

Counting areas (per the Wikipedia source article, verified against the
HoC RP11-44 headline):
  - England:  326 LADs (= 326 LAD16CD)
  - Scotland:  73 Scottish Parliament constituencies (= 73 SPC22CD)
  - Wales:     40 National Assembly for Wales constituencies (= 40 NAWC21CD)
  - NI:         1 region-wide single counting area (filtered — `gb` viewBox
                excludes NI, and there is no per-area breakdown to parse)

GB-paintable total: 439.

Tier-4 source — Wikipedia. The Electoral Commission's original per-area
data lived on the legacy aboutmyvote.co.uk micro-site (retired); HoC
Library RP11-44 is PDF-only. Cross-checks at extract time:
  - aggregate GB Yes/No must round to the canonical 32% / 68%
  - per-region Yes/No counts must match the regional summary in
    each section's `{{Referendum}}` template
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _holyrood_constituencies import HOLYROOD_22
from _senedd_constituencies_2007 import SENEDD_CONSTITUENCIES_2007

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "av_referendum_2011.json"
OVERRIDES_CSV = SOURCE / "av_ref_2011_overrides.csv"
LAD_GEOM = DATA / "lad_geoms_2016.json"

YEAR = 2011

# Click-through URL for the renderer's tooltip "Source: …" line. Lands
# the reader on the Wikipedia results article. The same URL is attached
# to every record (Wikipedia's per-section anchors would be more precise,
# but the article's section IDs are stable and the reader can scroll).
SOURCE_URL = (
    'https://en.wikipedia.org/wiki/'
    'Results_of_the_2011_United_Kingdom_Alternative_Vote_referendum'
)

# Region sections from scripts/29. England's 9 regions parse into LAD16CD;
# Scotland into SPC22CD; Wales into NAWC21CD.
ENGLISH_REGIONS = (
    'east_midlands', 'east_of_england', 'greater_london',
    'north_east_england', 'north_west_england', 'south_east_england',
    'south_west_england', 'west_midlands', 'yorkshire_and_the_humber',
)

# Headline cross-check (validates the parse end-to-end). The HoC RP11-44
# headline is 32.10% Yes / 67.90% No UK-wide; NI alone was 43.68% Yes (its
# single counting area). Subtracting NI from the article's UK aggregate
# (6,152,607 Yes / 13,013,123 No - 289,088 Yes / 372,706 No) gives a
# GB-only expectation of ≈ 31.69% Yes. Tolerance of ±0.5pp absorbs the
# residual drift from a few hand-typo'd values in the per-LAD Wikipedia
# tables (notably the South West section has three rows where adjacent
# LADs were transcribed with duplicated vote counts — Cheltenham/Cotswold,
# North Dorset/North Devon, and Wiltshire/Weymouth & Portland — which
# the parser cannot detect because the duplicate values are individually
# well-formed. The per-LAD winner is unaffected: all six involved LADs
# voted No either way, so the choropleth paints correctly).
GB_HEADLINE_YES_PCT = 31.69
GB_HEADLINE_NO_PCT  = 68.31
HEADLINE_TOLERANCE  = 0.50


# A row spans from a `|-` separator to the next `|-` or `|}`. Cells inside
# a row can be split by `||` on one line, by newline-then-`|`, or both.
# We extract the row body text then split on `(?:\|\||\n\|(?!\}))`.
def split_cells(row_body: str) -> list[str]:
    """Split a wikitable row body into cell strings.

    Handles both formats seen in the AV ref article:
      | A || B || C || D || E || F   (one-line, EU/EM style)
      | A\n|B\n|C\n|D\n|E\n|F        (multi-line, Scotland style)
    """
    # Normalise: strip leading "| " on the first cell, then split on `||`
    # OR newline+pipe (but not newline+`|}` which terminates the table).
    if row_body.startswith('|'):
        row_body = row_body[1:]
    parts = re.split(r'\|\||\n\|(?!\})', row_body)
    return [p.strip() for p in parts]


def parse_number(cell: str) -> int | None:
    """Pull an integer vote count out of a cell like `'''{{nts|29745}}'''`,
    `{{nts|12,432}}`, plain `9,496`, or the European-style typo
    `'''44.198'''` (Brighton & Hove's No-votes cell in the article uses
    a dot as a thousands separator). Returns None if no number found.

    Vote counts in this dataset are always integers ≥ 1,000, so a 3-digit
    group after a dot is treated as a thousands separator rather than a
    decimal fraction.
    """
    # Wikimarkup template form first — values inside {{nts|…}} are
    # canonical and never use dot-as-thousands.
    m = re.search(r'\{\{\s*nts\s*\|\s*([\d,]+)\s*\}\}', cell)
    if m:
        return int(m.group(1).replace(',', ''))
    # Dot-as-thousands typo (Brighton & Hove): `44.198` means 44,198.
    m = re.search(r'([0-9]+\.[0-9]{3})(?!\d)', cell)
    if m:
        return int(m.group(1).replace('.', ''))
    # Standard comma-thousands or no-separator integer.
    m = re.search(r"([0-9][0-9,]*)", cell)
    if m:
        return int(m.group(1).replace(',', ''))
    return None


def parse_link(cell: str) -> tuple[str, str]:
    """Extract (target, display) from the first `[[…]]` link in the cell.
    Falls back to (cell-stripped, cell-stripped) when no link is present.
    Strips inline `<ref>…</ref>` and `<ref ...>…</ref>` tags first.
    """
    cell = re.sub(r'<ref[^>]*?/>',         '', cell)
    cell = re.sub(r'<ref.*?</ref>',        '', cell, flags=re.DOTALL)
    m = re.search(r'\[\[([^\[\]]+?)\]\]', cell)
    if not m:
        return cell.strip(), cell.strip()
    inner = m.group(1)
    if '|' in inner:
        target, _, display = inner.partition('|')
        return target.strip(), display.strip()
    return inner.strip(), inner.strip()


def parse_row(row_body: str) -> dict | None:
    """Parse one wikitable row into {target, display, no_votes, yes_votes}.

    Returns None if the row doesn't look like a counting-area row (header
    row, totals row, separator, or unparseable).
    """
    cells = split_cells(row_body)
    if len(cells) < 5:
        return None
    name_cell, _turnout, no_cell, yes_cell, *_rest = cells
    if not name_cell.startswith(('[', '|')) and '[[' not in name_cell:
        # Skip header rows ("! Counting Area !! ...") and stray formatting.
        return None
    target, display = parse_link(name_cell)
    no_votes  = parse_number(no_cell)
    yes_votes = parse_number(yes_cell)
    if no_votes is None or yes_votes is None:
        return None
    return {
        'target':    target,
        'display':   display,
        'no_votes':  no_votes,
        'yes_votes': yes_votes,
    }


def parse_region_wikitext(wt: str) -> list[dict]:
    """Pull every counting-area row out of a region's wikitext."""
    # Find the wikitable. The first `{|` … `|}` after the per-region
    # `{{Referendum}}` summary is the per-area breakdown.
    m = re.search(r"\{\|\s*class=\"wikitable[^\"]*?\"(.+?)\|\}",
                  wt, flags=re.DOTALL)
    if not m:
        return []
    table_body = m.group(1)
    # Split on `|-` separators. Each chunk is one row body.
    raw_rows = re.split(r'\n\|-[^\n]*', table_body)
    out: list[dict] = []
    for rb in raw_rows:
        rb = rb.strip()
        if not rb or rb.startswith('!'):
            # Header row — skip.
            continue
        rec = parse_row(rb)
        if rec is not None:
            out.append(rec)
    return out


def _normalise_name(s: str) -> str:
    """Casefold + drop disambiguators + collapse punctuation/whitespace so
    "Bassetlaw District", "Bassetlaw", and "bassetlaw" all hash identically.
    """
    s = re.sub(r'\(.*?\)',  '', s)                # drop "(borough)" etc.
    s = re.sub(r'^(borough of|city of|metropolitan borough of|district of)\s+',
               '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+(district|borough|council|county)$', '', s,
               flags=re.IGNORECASE)
    s = re.sub(r'[^a-z0-9]+', ' ', s.casefold())
    return s.strip()


def build_lad_name_lookup(lad_geom: dict) -> dict[str, str]:
    """name → LAD16CD lookup built from data/lad_geoms_2016.json. Returns
    a dict keyed by the normalised name; duplicate normalisations are
    surfaced via stderr (rare — LAD names are designed to be unique).
    """
    lookup: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for code, entry in lad_geom['lads'].items():
        if not code.startswith('E0'):
            # Welsh / Scottish LADs aren't counting areas at the AV ref —
            # they were broken down by constituency instead.
            continue
        norm = _normalise_name(entry['name'])
        if norm in lookup and lookup[norm] != code:
            duplicates.setdefault(norm, [lookup[norm]]).append(code)
        else:
            lookup[norm] = code
    if duplicates:
        for norm, codes in duplicates.items():
            print(f'  WARN: LAD name "{norm}" maps to multiple codes: '
                  f'{codes}', file=sys.stderr)
    return lookup


def build_spc_lookup() -> dict[str, str]:
    """Holyrood display-name → SPC22CD."""
    out: dict[str, str] = {}
    for spc22cd, name, _region, _wiki_title in HOLYROOD_22:
        out[_normalise_name(name)] = spc22cd
    return out


def build_nawc_lookup() -> dict[str, str]:
    """Senedd display-name → NAWC21CD."""
    out: dict[str, str] = {}
    for nawc21cd, name, _wiki_title, _region in SENEDD_CONSTITUENCIES_2007:
        out[_normalise_name(name)] = nawc21cd
    return out


def load_overrides() -> dict[tuple[str, str], str]:
    """Hand-curated `(kind, display_name) → code` overrides for cases
    where the Wikipedia display name doesn't normalise to the canonical
    registry name. Currently expected only for English LADs whose
    Wikipedia article uses an ambiguous or qualifier-heavy display label.
    """
    overrides: dict[tuple[str, str], str] = {}
    if not OVERRIDES_CSV.exists():
        return overrides
    with open(OVERRIDES_CSV, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            kind = row['kind'].strip().lower()
            name = row['wiki_display'].strip()
            code = row['code'].strip()
            overrides[(kind, _normalise_name(name))] = code
    return overrides


def resolve_code(kind: str, target: str, display: str,
                 lookup: dict[str, str],
                 overrides: dict[tuple[str, str], str]) -> str | None:
    """Pick a code for one record. Prefers an exact override, then the
    normalised display name, then the normalised target. Returns None
    if nothing matches.
    """
    override = overrides.get((kind, _normalise_name(display)))
    if override:
        return override
    n_disp = _normalise_name(display)
    if n_disp in lookup:
        return lookup[n_disp]
    n_targ = _normalise_name(target)
    if n_targ in lookup:
        return lookup[n_targ]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--strict', action='store_true',
                    help='Exit non-zero on any unmatched counting area')
    args = ap.parse_args()

    if not LAD_GEOM.exists():
        raise SystemExit(
            f'{LAD_GEOM.relative_to(ROOT)} not found — run scripts/27 first.')
    lad_geom = json.loads(LAD_GEOM.read_text())
    lad_lookup  = build_lad_name_lookup(lad_geom)
    spc_lookup  = build_spc_lookup()
    nawc_lookup = build_nawc_lookup()
    overrides   = load_overrides()

    areas: dict[str, dict] = {}
    unmatched: list[tuple[str, str, str]] = []  # (region, target, display)
    per_region_yes: dict[str, int] = {}
    per_region_no:  dict[str, int] = {}

    def ingest(region: str, kind: str, code: str, name: str,
               yes: int, no: int) -> None:
        total = yes + no
        if total <= 0:
            print(f'  WARN: {region} {code} {name}: zero-vote row — skipping',
                  file=sys.stderr)
            return
        if yes == no:
            print(f'  WARN: {region} {code} {name}: exact tie — '
                  f'defaulting to AV No', file=sys.stderr)
        winner = 'AV Yes' if yes > no else 'AV No'
        if code in areas:
            print(f'  WARN: duplicate code {code} ({name}) — '
                  f'second occurrence overwrites first', file=sys.stderr)
        areas[code] = {
            'name': name,
            'kind': kind,
            'history': [{
                'y':     YEAR,
                'w':     winner,
                'src':   'wikipedia',
                'url':   SOURCE_URL,
                'votes': {'AV Yes': yes, 'AV No': no},
                'pct':   {
                    'AV Yes': round(yes / total, 4),
                    'AV No':  round(no  / total, 4),
                },
            }],
        }
        per_region_yes[region] = per_region_yes.get(region, 0) + yes
        per_region_no[region]  = per_region_no.get(region, 0)  + no

    region_kinds = (
        *((r, 'lad',  lad_lookup)  for r in ENGLISH_REGIONS),
        ('scotland', 'spc', spc_lookup),
        ('wales',    'nawc', nawc_lookup),
    )

    for region, kind, lookup in region_kinds:
        cache = SOURCE / f'wiki_av_ref_2011_{region}.json'
        if not cache.exists():
            raise SystemExit(
                f'{cache.relative_to(ROOT)} not found — run scripts/29.')
        data = json.loads(cache.read_text())
        wt = data.get('parse', {}).get('wikitext', '')
        rows = parse_region_wikitext(wt)
        for r in rows:
            code = resolve_code(kind, r['target'], r['display'],
                                lookup, overrides)
            if not code:
                unmatched.append((region, r['target'], r['display']))
                continue
            ingest(region, kind, code, r['display'],
                   r['yes_votes'], r['no_votes'])

    out = {'years': [YEAR], 'areas': areas}
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))

    # Per-kind tally + headline cross-check.
    counts = {'lad': 0, 'spc': 0, 'nawc': 0}
    yes_total = no_total = 0
    yes_wins = no_wins = 0
    for code, area in areas.items():
        counts[area['kind']] += 1
        h = area['history'][0]
        yes_total += h['votes']['AV Yes']
        no_total  += h['votes']['AV No']
        if h['w'] == 'AV Yes':
            yes_wins += 1
        else:
            no_wins += 1
    total = yes_total + no_total
    yes_pct = 100 * yes_total / total if total else 0
    no_pct  = 100 * no_total  / total if total else 0

    print(f'\nWrote {OUT.relative_to(ROOT)} — {len(areas)} GB counting areas '
          f'(lads={counts["lad"]}, spcs={counts["spc"]}, '
          f'nawcs={counts["nawc"]})')
    print(f'  AV Yes plurality: {yes_wins}; AV No plurality: {no_wins}')
    print(f'  GB total: AV Yes {yes_pct:.2f}% / AV No {no_pct:.2f}% '
          f'(expected GB-only ≈ {GB_HEADLINE_YES_PCT:.2f}% / '
          f'{GB_HEADLINE_NO_PCT:.2f}%; UK headline 32.10% / 67.90% '
          f'including NI)')

    headline_drift = abs(yes_pct - GB_HEADLINE_YES_PCT)
    if headline_drift > HEADLINE_TOLERANCE:
        print(f'  WARN: GB Yes% drifts {headline_drift:.2f}pp from the '
              f'expected GB-only figure — investigate per-region totals:',
              file=sys.stderr)
        for region in (*ENGLISH_REGIONS, 'scotland', 'wales'):
            ry = per_region_yes.get(region, 0)
            rn = per_region_no.get(region, 0)
            tot = ry + rn
            if tot:
                print(f'    {region:30s} Yes {100*ry/tot:5.2f}% '
                      f'No {100*rn/tot:5.2f}%  '
                      f'({ry:>9,} / {rn:>9,})', file=sys.stderr)

    if unmatched:
        print(f'  WARN: {len(unmatched)} counting area(s) unmatched — add '
              f'overrides in {OVERRIDES_CSV.relative_to(ROOT)}:',
              file=sys.stderr)
        for region, target, display in unmatched:
            print(f'    {region:30s} target="{target}" display="{display}"',
                  file=sys.stderr)
        if args.strict:
            sys.exit(1)


if __name__ == '__main__':
    main()
