"""Build the per-CED per-year history dataset for the GB Current map page's
time slider (issue #69 Phase 1B / #73).

Sibling of scripts/04d_build_ward_history.py — same three-pass shape, but
keyed by CED polygon instead of WD24 ward. Where 04c collapses every CED to
a single most-recent record (in data/ced_winners.json), 04e keeps the full
per-year history so the slider can rewind from 2026 back to 2017 with
era-appropriate polygons.

Sources, per (polygon, year) precedence (first-write-wins within each pass,
official outranks wiki):
  1. data/source/county_official_<year>.csv — authoritative council results.
  2. data/county_results_2026_ceds.json — Wikipedia 2026 parsings (01c).
  3. wiki_current_articles parsed by scripts/_wiki_history — every prior
     contest with a cached article (2017+2021+2025).

Polygon era matching (which years a polygon can accept):
  - bare E25CD (CED25, unchanged 17 counties) → all slider years.
  - LGBCE_<cty>_* (Norfolk/Essex/Suffolk post-2026 review) → year >= 2026.
  - PRE_<cty>_* (the four counties whose 2017/2021 boundaries differ from
    the 2025/2026 set) → year < 2026.

Output: data/ced_history.json with schema:
  { "years": [2017, 2021, 2025, 2026],
    "ceds": { "<polygon_key>": {
        "county": "Norfolk",
        "division": "Acle ED",
        "cty": "E10000020",
        "history": [ {y, w, src, url} ... ascending by year ]
    } } }

Determinism: sort_keys=True on json.dump, per-CED history ascending by year.
"""
import csv
import importlib
import json
import re
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

from _councils import for_region
from _wiki_history import iter_council_year_records, pick_parser

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"

# County-tier year stops the slider exposes for the CED layer. English
# county elections run on a 4-year cycle (2017, 2021, 2025, 2026 for the
# 14 non-2026 + 6 × 2026-contested split). Slider stops in 04d include
# the off-years (2018, 2019, ...) for the ward layer; CED history doesn't.
SLIDER_YEARS = [2017, 2021, 2025, 2026]

# Source rank — lower is better. First-write-wins per (polygon, year),
# but a later pass can overwrite an earlier one if it has a better rank.
SOURCE_RANK = {'official_county': 0, 'wiki_2026': 1, 'wiki': 2}


def wikipedia_url(title: str) -> str:
    """Same convention as 04d.wikipedia_url."""
    return f'https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(" ", "_"), safe="_,()/")}'


def import_04c():
    sys.path.insert(0, str(ROOT / "scripts"))
    return importlib.import_module('04c_build_current_winners')


def polygon_accept_years(polygon_key: str) -> set[int]:
    """Slider years for which this polygon represents the legal-effect boundaries."""
    if polygon_key.startswith('PRE_'):
        return {y for y in SLIDER_YEARS if y < 2026}
    if polygon_key.startswith('LGBCE_'):
        return {y for y in SLIDER_YEARS if y >= 2026}
    return set(SLIDER_YEARS)


def main():
    h04c = import_04c()
    normalise_ced = h04c.normalise_ced
    load_ced_overrides = h04c.load_ced_overrides

    with open(DATA / 'ward_geoms.json') as f:
        geoms = json.load(f)

    ced_overrides = load_ced_overrides()

    # Build per-county article-title lookup so each wiki record can carry
    # its source URL — same shape 04d uses.
    article_titles_by_lad_year: dict[tuple[str, int], str] = {}
    council_by_lad: dict[str, dict] = {}
    for council in for_region('gb'):
        if not council['lad_code'].startswith('E10'):
            continue
        council_by_lad[council['lad_code']] = council
        for entry in (council.get('wiki_current_articles') or []):
            article_titles_by_lad_year[(council['lad_code'], entry['year'])] = entry['title']
        # 2026 contest URL lives on `wiki_2026` for the 6 × 2026-contested
        # counties — fold it into the lookup so Pass 1 (wiki_2026 records)
        # also gets clickable URLs.
        if council.get('wiki_2026'):
            article_titles_by_lad_year.setdefault(
                (council['lad_code'], 2026), council['wiki_2026']
            )

    # source_records[(cty, name_norm, year)] = list[(party, src_tag, url)]
    source_records: dict[tuple[str, str, int], list[tuple[str, str, str]]] = defaultdict(list)

    # --- Pass 0: official CSVs, all years. Authoritative. ---
    pass0_added = 0
    for path in sorted(SOURCE.glob('county_official_*.csv')):
        m = re.match(r'county_official_(\d{4})\.csv$', path.name)
        if not m:
            continue
        year = int(m.group(1))
        with open(path, newline='') as f:
            for row in csv.DictReader(f):
                if not row.get('party') or not row.get('division'):
                    continue
                lad = row['lad_code']
                council = council_by_lad.get(lad)
                official_url = (council or {}).get('official_url') or ''
                key = (lad, normalise_ced(row['division']), year)
                source_records[key].append((row['party'], 'official_county', official_url))
                pass0_added += 1

    # --- Pass 1: county_results_2026_ceds.json — Wikipedia 2026 parsings. ---
    # Keyed by human county name → {ced_name: {party, year, district}}. Convert
    # to the (lad, name_norm, year) shape so the join is uniform.
    pass1_added = 0
    p_2026 = DATA / 'county_results_2026_ceds.json'
    data_2026 = json.loads(p_2026.read_text()) if p_2026.exists() else {}
    # county-name → lad mapping for the 6 × 2026-contested counties.
    lad_by_county_name: dict[str, str] = {
        c['name']: c['lad_code']
        for c in council_by_lad.values()
    }
    for county_name, ceds in data_2026.items():
        lad = lad_by_county_name.get(county_name)
        if lad is None:
            continue
        title = article_titles_by_lad_year.get((lad, 2026), '')
        url = wikipedia_url(title) if title else ''
        for ced_name, rec in ceds.items():
            year = rec.get('year') or 2026
            party = rec.get('party')
            if not party:
                continue
            key = (lad, normalise_ced(ced_name), year)
            source_records[key].append((party, 'wiki_2026', url))
            pass1_added += 1

    # --- Pass 2: iter_council_year_records — every prior contest with a
    #     cached article. For E10 councils this yields per-CED records. ---
    pass2_added = 0
    for council in council_by_lad.values():
        _parser, is_county = pick_parser(council)
        if not is_county:
            continue
        lad = council['lad_code']
        for year, ced_name, rec in iter_council_year_records(council):
            party = rec.get('party')
            if not party:
                continue
            title = article_titles_by_lad_year.get((lad, year), '')
            url = wikipedia_url(title) if title else ''
            key = (lad, normalise_ced(ced_name), year)
            source_records[key].append((party, 'wiki', url))
            pass2_added += 1

    # --- Join: walk polygons and find the best record per (polygon, year). ---
    ceds_main = geoms.get('ceds', {})
    ceds_pre = geoms.get('ceds_pre_review', {})

    history: dict[str, dict[int, dict]] = {}
    polygon_meta: dict[str, dict] = {}

    # Per-county counters for the stderr summary.
    per_cty_matched: dict[str, int] = defaultdict(int)
    per_cty_no_winner: dict[str, int] = defaultdict(int)
    per_cty_overrides: dict[str, int] = defaultdict(int)

    def lookup(cty: str, name_norm: str, year: int) -> tuple[str, str, str] | None:
        recs = source_records.get((cty, name_norm, year))
        if recs:
            return min(recs, key=lambda r: SOURCE_RANK.get(r[1], 99))
        return None

    def join_one(polygon_key: str, meta: dict):
        cty = meta.get('cty', '')
        if not cty.startswith('E10'):
            # We never paint non-E10 polygons in the CED layer (some Welsh
            # principal areas leak `cty` keys via 09b, but they're not in scope).
            return
        cty_name = meta.get('cty_name', '') or ''
        cty_clean = re.sub(r'\s+County\s*$', '', cty_name)
        name_norm = normalise_ced(meta.get('name', ''))
        polygon_meta[polygon_key] = {
            'cty':      cty,
            'county':   cty_clean,
            'division': meta.get('name', ''),
        }
        accept = polygon_accept_years(polygon_key)
        per_year: dict[int, dict] = {}
        for year in sorted(accept):
            best = lookup(cty, name_norm, year)
            matched_via_override = False
            if best is None:
                override_target = ced_overrides.get((cty, name_norm))
                if override_target is not None:
                    best = lookup(cty, override_target, year)
                    matched_via_override = best is not None
            if best is None:
                continue
            party, src, url = best
            per_year[year] = {'y': year, 'w': party, 'src': src, 'url': url}
            if matched_via_override:
                per_cty_overrides[cty] += 1
        history[polygon_key] = per_year
        if per_year:
            per_cty_matched[cty] += 1
        else:
            per_cty_no_winner[cty] += 1

    for k, m in ceds_main.items():
        join_one(k, m)
    for k, m in ceds_pre.items():
        join_one(k, m)

    # --- Output assembly ---
    out_ceds: dict[str, dict] = {}
    for polygon_key, per_year in history.items():
        meta = polygon_meta[polygon_key]
        entries = sorted(per_year.values(), key=lambda e: e['y'])
        out_ceds[polygon_key] = {
            'county':   meta['county'],
            'cty':      meta['cty'],
            'division': meta['division'],
            'history':  entries,
        }

    all_years_in_data = {e['y'] for per_year in history.values()
                          for e in per_year.values()}
    present_years = sorted(set(SLIDER_YEARS) & all_years_in_data)

    out = {'years': present_years, 'ceds': out_ceds}
    with open(DATA / 'ced_history.json', 'w') as f:
        json.dump(out, f, sort_keys=True, separators=(',', ':'))

    total_polys = len(out_ceds)
    total_ced_years = sum(len(c['history']) for c in out_ceds.values())
    per_year_coverage: dict[int, int] = defaultdict(int)
    for c in out_ceds.values():
        for e in c['history']:
            per_year_coverage[e['y']] += 1
    print(f'Wrote ced_history.json — {total_polys:,} CED polygons, '
          f'{len(present_years)} year stops, {total_ced_years:,} CED-years')
    print(f'  passes: 0={pass0_added:,} (county_official), '
          f'1={pass1_added:,} (wiki_2026), 2={pass2_added:,} (wiki history)')
    print('  per-year coverage: ' + ' · '.join(
        f'{y}: {per_year_coverage.get(y, 0):,}' for y in present_years
    ))
    # Per-county summary (one line per E10) so missing-history wards are
    # immediately visible during dev iteration.
    print('  per-county polygon coverage (matched / no_winner / via_override):')
    for cty in sorted(set(per_cty_matched) | set(per_cty_no_winner)):
        cty_label = next(
            (c['name'] for c in council_by_lad.values() if c['lad_code'] == cty),
            cty,
        )
        m = per_cty_matched.get(cty, 0)
        nw = per_cty_no_winner.get(cty, 0)
        ov = per_cty_overrides.get(cty, 0)
        flag = '' if nw == 0 else f'  ← {nw} grey'
        print(f'    {cty_label:>18} ({cty}): {m:3d} / {nw:2d} / {ov:2d}{flag}')


if __name__ == '__main__':
    main()
