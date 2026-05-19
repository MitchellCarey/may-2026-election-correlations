"""Build the per-constituency + per-region history dataset for the GB
Current map page's Senedd time-slider repaint (issue #69 Phase 1D / #72).

Sibling of scripts/04f_build_holyrood_history.py — same three-pass
shape on the constituency side, plus a fourth pass for region records
(d'Hondt regional list seats per region per year).

Sources, per (polygon, year) precedence (later passes win on tie):
  1. data/source/senedd_official_<year>.csv — optional hand-curated
     fallback for Wikipedia content gaps. Schema:
       nawc21cd,year,party,candidate,source,url,note
     (Currently empty — landed as a pattern for future curation.)
  2. data/senedd_history_raw.json kind="fptp" — Wikipedia per-
     constituency extractions for 2016 + 2021 (output of scripts/15b).
  3. data/senedd_2026.json — Wikipedia 2026 results (output of
     scripts/15). Routes to current S0x polygons.

Polygon era matching:
  - bare S01..S16 in senedd_geoms.json `constituencies`           → 2026.
  - PRE_W09000*** in senedd_geoms_2007.json `constituencies`     → year < 2026.

Region records flow through unchanged from 15b's regional pass; the
per-region history block is keyed by display name (the same name used
in the registry's 4th field, e.g. "North Wales") and applies only to
pre-review reads (2016 + 2021 — there are no per-region "list seats"
under the 2026 closed-list 16-constituency layout).

Output: data/senedd_history.json with schema:
  { "years": [2016, 2021, 2026],
    "constituencies": { "<polygon_key>": {
        "name":    "Aberavon",
        "region":  "South Wales West",
        "history": [ {y, w, src, url, candidate?} ... ascending by year ] } },
    "regions": { "<region_name>": {
        "history": [ {y, seats, seats_raw, src, url} ... ascending by year ] } } }

Determinism: sort_keys=True on json.dump, per-key history ascending by year.
"""
import argparse
import csv
import json
import re
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _senedd_constituencies_2007 import SENEDD_CONSTITUENCIES_2007
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"

# Senedd-tier year stops the slider exposes. Welsh elections run on a
# 5-year cycle (2016, 2021 under the old 40-seat AMS layout; 2026 under
# the new 16-seat closed-list layout). Pre-2016 contests are out of
# scope for Phase 1D.
SLIDER_YEARS = [2016, 2021, 2026]

# Source rank — higher number wins. Mirrors 04f's per-polygon dedup.
SOURCE_RANK = {'wiki': 0, 'official': 1}


def wikipedia_url(title: str) -> str:
    """Same convention as 04d / 04e / 04f."""
    return f'https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(" ", "_"), safe="_,()/")}'


# Used by Pass 2 to recover the source URL for 2026 records (15 doesn't
# carry per-constituency URLs into senedd_2026.json — it parses one
# Wikipedia article per constituency, with the registry's wiki_title).
# The 2026 registry is unrelated to the 2007 registry; the wiki_title
# for a 2026 constituency lives in scripts/_senedd_constituencies.py.
from _senedd_constituencies import SENEDD_CONSTITUENCIES as _SENEDD_2026
_URLS_2026 = {c: wikipedia_url(t) for c, _n, t in _SENEDD_2026}


def url_for_2026(code: str) -> str:
    return _URLS_2026.get(code, '')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.parse_args()

    # --- Inputs ---
    geoms_2026 = json.loads((DATA / 'senedd_geoms.json').read_text())
    geoms_2007 = json.loads((DATA / 'senedd_geoms_2007.json').read_text())
    senedd_2026 = json.loads((DATA / 'senedd_2026.json').read_text())
    raw_path = DATA / 'senedd_history_raw.json'
    raw_records = json.loads(raw_path.read_text()) if raw_path.exists() else []

    current_keys = set(geoms_2026.get('constituencies', {}).keys())  # S01..S16
    pre_keys = set(geoms_2007.get('constituencies', {}).keys())      # W09000001..

    if not current_keys:
        raise SystemExit('senedd_geoms.json has no `constituencies` — run 16 first.')
    if not pre_keys:
        raise SystemExit('senedd_geoms_2007.json has no `constituencies` — run 16b first.')

    # Registry meta for pre-review polygons (name + region).
    reg_meta_by_code = {
        code: {'name': name, 'region': region}
        for code, name, _wiki, region in SENEDD_CONSTITUENCIES_2007
    }

    # Constituency-side history: polygon_key → year → entry dict.
    cons_history: dict[str, dict[int, dict]] = defaultdict(dict)
    polygon_meta: dict[str, dict] = {}

    def upsert(polygon_key: str, year: int, entry: dict, src_tag: str):
        prev = cons_history[polygon_key].get(year)
        if prev and SOURCE_RANK.get(src_tag, -1) <= SOURCE_RANK.get(prev.get('src', ''), -1):
            return
        cons_history[polygon_key][year] = {**entry, 'src': src_tag}

    # --- Polygon meta — pre-review polygons (from registry) ---
    for code in pre_keys:
        meta = reg_meta_by_code.get(code, {})
        polygon_meta[f'PRE_{code}'] = {
            'name':   meta.get('name', code),
            'region': meta.get('region', ''),
        }

    # --- Polygon meta — current (2026) polygons (from geom file) ---
    for code, info in geoms_2026.get('constituencies', {}).items():
        polygon_meta[code] = {
            'name':   info.get('name', code),
            'region': '',  # 2026 has no regional list / no region mapping
        }

    # --- Pass 1: Wikipedia 2016 + 2021 per-constituency extractions ---
    pass1_added = 0
    for rec in raw_records:
        if rec.get('kind') != 'fptp':
            continue
        nawc21cd = rec['nawc21cd']
        year = rec['year']
        if year not in SLIDER_YEARS:
            continue
        polygon_key = f'PRE_{nawc21cd}'
        if nawc21cd not in pre_keys:
            print(f'  WARN: raw fptp record for {nawc21cd} {year} has no '
                  f'pre-review polygon', file=sys.stderr)
            continue
        if not rec.get('winner'):
            continue
        upsert(polygon_key, year, {
            'y':         year,
            'w':         rec['winner'],
            'url':       rec.get('url', ''),
            'candidate': rec.get('candidate'),
        }, 'wiki')
        pass1_added += 1

    # --- Pass 2: Wikipedia 2026 consolidated extraction ---
    pass2_added = 0
    for rec in senedd_2026:
        code = rec['code']
        if code not in current_keys:
            print(f'  WARN: 2026 record {code} has no current polygon',
                  file=sys.stderr)
            continue
        plurality = rec.get('plurality_party')
        if not plurality:
            continue
        upsert(code, 2026, {
            'y':         2026,
            'w':         plurality,
            'url':       url_for_2026(code),
            'candidate': None,
        }, 'wiki')
        pass2_added += 1

    # --- Pass 3: Hand-curated senedd_official_<year>.csv fallbacks ---
    # Schema: nawc21cd,year,party,candidate,source,url,note
    pass3_added = 0
    for path in sorted(SOURCE.glob('senedd_official_*.csv')):
        m = re.match(r'senedd_official_(\d{4})\.csv$', path.name)
        if not m:
            continue
        year = int(m.group(1))
        if year not in SLIDER_YEARS:
            continue
        with path.open(newline='') as f:
            for row in csv.DictReader(f):
                nawc21cd = (row.get('nawc21cd') or '').strip()
                party = (row.get('party') or '').strip()
                if not nawc21cd or not party:
                    continue
                # Pre-review polygons (W09000***) cover 2016/2021;
                # the 2026 review used new S0x codes that aren't in
                # the CSV namespace. Hand curation is for pre-review only.
                if year >= 2026:
                    print(f'  WARN: senedd_official_{year}.csv row references '
                          f'pre-review code {nawc21cd} at year {year} — skipped',
                          file=sys.stderr)
                    continue
                polygon_key = f'PRE_{nawc21cd}'
                if nawc21cd not in pre_keys:
                    print(f'  WARN: official row {nawc21cd} {year} has no '
                          f'pre-review polygon', file=sys.stderr)
                    continue
                upsert(polygon_key, year, {
                    'y':         year,
                    'w':         normalize_party(party),
                    'url':       (row.get('url') or '').strip(),
                    'candidate': (row.get('candidate') or '').strip() or None,
                }, 'official')
                pass3_added += 1

    # --- Pass 4: Region records (regional list seats per region per year) ---
    regions_history: dict[str, dict[int, dict]] = defaultdict(dict)
    pass4_added = 0
    for rec in raw_records:
        if rec.get('kind') != 'regional':
            continue
        region = rec['region']
        year = rec['year']
        if year not in SLIDER_YEARS:
            continue
        regions_history[region][year] = {
            'y':         year,
            'seats':     rec['seats'],
            'seats_raw': rec.get('seats_raw') or {},
            'url':       rec.get('url', ''),
            'src':       'wiki',
        }
        pass4_added += 1

    # --- Output assembly ---
    out_constituencies: dict[str, dict] = {}
    for polygon_key, per_year in cons_history.items():
        meta = polygon_meta.get(polygon_key, {})
        entries = []
        for entry in sorted(per_year.values(), key=lambda e: e['y']):
            clean = {'y': entry['y'], 'w': entry['w'],
                     'src': entry['src'], 'url': entry.get('url', '')}
            if entry.get('candidate'):
                clean['candidate'] = entry['candidate']
            entries.append(clean)
        out_constituencies[polygon_key] = {
            'name':    meta.get('name', ''),
            'region':  meta.get('region', ''),
            'history': entries,
        }

    out_regions: dict[str, dict] = {}
    for region, per_year in regions_history.items():
        entries = []
        for entry in sorted(per_year.values(), key=lambda e: e['y']):
            entries.append({
                'y':         entry['y'],
                'seats':     entry['seats'],
                'seats_raw': entry['seats_raw'],
                'src':       entry['src'],
                'url':       entry.get('url', ''),
            })
        out_regions[region] = {'history': entries}

    all_years_in_cons = {e['y'] for per_year in cons_history.values()
                              for e in per_year.values()}
    all_years_in_reg = {e['y'] for per_year in regions_history.values()
                              for e in per_year.values()}
    present_years = sorted(set(SLIDER_YEARS) & (all_years_in_cons | all_years_in_reg))

    out = {
        'years':          present_years,
        'constituencies': out_constituencies,
        'regions':        out_regions,
    }
    with open(DATA / 'senedd_history.json', 'w') as f:
        json.dump(out, f, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

    total_cons = len(out_constituencies)
    total_cons_years = sum(len(c['history']) for c in out_constituencies.values())
    total_reg = len(out_regions)
    total_reg_years = sum(len(r['history']) for r in out_regions.values())
    per_year_cov_cons: dict[int, int] = defaultdict(int)
    per_year_cov_reg: dict[int, int] = defaultdict(int)
    for c in out_constituencies.values():
        for e in c['history']:
            per_year_cov_cons[e['y']] += 1
    for r in out_regions.values():
        for e in r['history']:
            per_year_cov_reg[e['y']] += 1
    print(f'Wrote senedd_history.json — {total_cons} constituency polygons, '
          f'{total_reg} regions, {len(present_years)} year stops')
    print(f'  constituency-years: {total_cons_years} '
          f'(passes: 1={pass1_added} wiki 2016+2021, '
          f'2={pass2_added} wiki 2026, 3={pass3_added} hand-curated)')
    print(f'  region-years:       {total_reg_years} '
          f'(pass: 4={pass4_added} wiki 2016+2021)')
    print('  per-year coverage (constituencies): ' + ' · '.join(
        f'{y}: {per_year_cov_cons.get(y, 0)}' for y in present_years
    ))
    print('  per-year coverage (regions):       ' + ' · '.join(
        f'{y}: {per_year_cov_reg.get(y, 0)}' for y in present_years
    ))

    # Per-region pre-review constituency coverage (mirrors 04f's per-region block).
    per_region_polys: dict[str, int] = defaultdict(int)
    per_region_grey: dict[str, int] = defaultdict(int)
    for polygon_key, c in out_constituencies.items():
        if not polygon_key.startswith('PRE_'):
            continue
        reg = c.get('region') or '(unknown)'
        per_region_polys[reg] += 1
        if not any(e['y'] in (2016, 2021) for e in c['history']):
            per_region_grey[reg] += 1
    if per_region_polys:
        print('  per-region pre-review coverage (polygons / with-history):')
        for reg in sorted(per_region_polys):
            n = per_region_polys[reg]
            grey = per_region_grey[reg]
            ok = n - grey
            flag = '' if grey == 0 else f'  ← {grey} grey'
            print(f'    {reg:>22}: {ok:2d} / {n:2d}{flag}')


if __name__ == '__main__':
    main()
