"""Build the per-constituency + per-region history dataset for the GB
Current map page's London Assembly time-slider repaint (issue #89).

Sibling of scripts/04g_build_senedd_history.py — same multi-pass shape
on the constituency side, plus a separate pass for region records (the
11 London-wide list seats allocated per year). Simpler than 04g because
there is exactly one "region" (Greater London) — the d'Hondt list runs
across the whole electorate, not per regional sub-electorate.

Sources, per (polygon, year) precedence (later passes win on tie):
  1. data/source/gla_assembly_official_<year>.csv — optional hand-curated
     fallback for Wikipedia content gaps. Schema:
       lac24cd,year,party,candidate,source,url,note
     (Currently empty — landed as a pattern for future curation.)
  2. data/gla_assembly_raw.json kind="fptp" — Wikipedia per-constituency
     extractions for 2012 / 2016 / 2021 / 2024 (output of scripts/30).

Polygon era matching is trivial: LAC boundaries haven't changed since
the GLA's creation in 2000, so the 14 E32* codes in
data/gla_assembly_geom.json cover every contest year — no PRE_ prefix
needed.

Output: data/gla_assembly_history.json with schema:
  { "years": [2012, 2016, 2021, 2024],
    "constituencies": { "<LAC24CD>": {
        "name":    "Barnet and Camden",
        "region":  "Greater London",
        "history": [ {y, w, src, url, candidate?} ... ascending by year ] } },
    "regions": { "Greater London": {
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

# Assembly-tier year stops the slider exposes. Four contests on a four-
# year cycle from 2012 (2020 was postponed to 2021 under coronavirus
# postponement regulations).
SLIDER_YEARS = [year for year, _ in GLA_ASSEMBLY_YEARS]

# Source rank — higher number wins. Mirrors 04g's per-polygon dedup.
SOURCE_RANK = {'wiki': 0, 'official': 1}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.parse_args()

    # --- Inputs ---
    geom_path = DATA / 'gla_assembly_geom.json'
    raw_path = DATA / 'gla_assembly_raw.json'
    if not geom_path.exists():
        raise SystemExit(f'{geom_path.relative_to(ROOT)} missing — run scripts/31 first.')
    if not raw_path.exists():
        raise SystemExit(f'{raw_path.relative_to(ROOT)} missing — run scripts/30 first.')

    geoms = json.loads(geom_path.read_text())
    raw_records = json.loads(raw_path.read_text())

    polygon_keys = set(geoms.get('constituencies', {}).keys())
    if not polygon_keys:
        raise SystemExit('gla_assembly_geom.json has no `constituencies` — '
                         'run 31 first.')

    # Registry meta keyed by LAC24CD (name + the single shared region).
    reg_meta_by_code = {
        code: {'name': name, 'region': GLA_ASSEMBLY_REGION_NAME}
        for code, name in GLA_ASSEMBLY_CONSTITUENCIES
    }

    # Constituency-side history: polygon_key → year → entry dict.
    cons_history: dict[str, dict[int, dict]] = defaultdict(dict)

    def upsert(polygon_key: str, year: int, entry: dict, src_tag: str):
        prev = cons_history[polygon_key].get(year)
        if prev and SOURCE_RANK.get(src_tag, -1) <= SOURCE_RANK.get(prev.get('src', ''), -1):
            return
        cons_history[polygon_key][year] = {**entry, 'src': src_tag}

    # --- Polygon meta — current polygons (from geom file) ---
    polygon_meta: dict[str, dict] = {}
    for code, info in geoms.get('constituencies', {}).items():
        polygon_meta[code] = {
            'name':   reg_meta_by_code.get(code, {}).get('name', info.get('name', code)),
            'region': GLA_ASSEMBLY_REGION_NAME,
        }

    # --- Pass 1: Wikipedia per-constituency extractions ---
    pass1_added = 0
    for rec in raw_records:
        if rec.get('kind') != 'fptp':
            continue
        code = rec['lac24cd']
        year = rec['year']
        if year not in SLIDER_YEARS:
            continue
        if code not in polygon_keys:
            print(f'  WARN: raw record for {code} {year} has no polygon',
                  file=sys.stderr)
            continue
        if not rec.get('winner'):
            continue
        upsert(code, year, {
            'y':         year,
            'w':         rec['winner'],
            'url':       rec.get('url', ''),
            'candidate': rec.get('candidate'),
        }, 'wiki')
        pass1_added += 1

    # --- Pass 2: Hand-curated gla_assembly_official_<year>.csv fallbacks ---
    # Schema: lac24cd,year,party,candidate,source,url,note
    pass2_added = 0
    for path in sorted(SOURCE.glob('gla_assembly_official_*.csv')):
        m = re.match(r'gla_assembly_official_(\d{4})\.csv$', path.name)
        if not m:
            continue
        year = int(m.group(1))
        if year not in SLIDER_YEARS:
            continue
        with path.open(newline='') as f:
            for row in csv.DictReader(f):
                code = (row.get('lac24cd') or '').strip()
                party = (row.get('party') or '').strip()
                if not code or not party:
                    continue
                if code not in polygon_keys:
                    print(f'  WARN: official row {code} {year} has no polygon',
                          file=sys.stderr)
                    continue
                upsert(code, year, {
                    'y':         year,
                    'w':         normalize_party(party),
                    'url':       (row.get('url') or '').strip(),
                    'candidate': (row.get('candidate') or '').strip() or None,
                }, 'official')
                pass2_added += 1

    # --- Pass 3: Region records (London-wide list seats per year) ---
    regions_history: dict[str, dict[int, dict]] = defaultdict(dict)
    pass3_added = 0
    for rec in raw_records:
        if rec.get('kind') != 'list':
            continue
        region = rec.get('region') or GLA_ASSEMBLY_REGION_NAME
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
        pass3_added += 1

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
            'region':  meta.get('region', GLA_ASSEMBLY_REGION_NAME),
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
    with open(DATA / 'gla_assembly_history.json', 'w') as f:
        json.dump(out, f, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

    total_cons = len(out_constituencies)
    total_cons_years = sum(len(c['history']) for c in out_constituencies.values())
    total_reg = len(out_regions)
    total_reg_years = sum(len(r['history']) for r in out_regions.values())
    per_year_cov_cons: dict[int, int] = defaultdict(int)
    per_year_cov_reg: dict[int, int] = defaultdict(int)
    list_seats_total: dict[int, int] = defaultdict(int)
    for c in out_constituencies.values():
        for e in c['history']:
            per_year_cov_cons[e['y']] += 1
    for r in out_regions.values():
        for e in r['history']:
            per_year_cov_reg[e['y']] += 1
            list_seats_total[e['y']] += sum(e['seats'].values())
    print(f'Wrote gla_assembly_history.json — {total_cons} constituencies, '
          f'{total_reg} region, {len(present_years)} year stops')
    print(f'  constituency-years: {total_cons_years} '
          f'(passes: 1={pass1_added} wiki, 2={pass2_added} hand-curated)')
    print(f'  region-years:       {total_reg_years} '
          f'(pass: 3={pass3_added} wiki list)')
    print('  per-year coverage (constituencies): ' + ' · '.join(
        f'{y}: {per_year_cov_cons.get(y, 0)}/14' for y in present_years
    ))
    print('  per-year list-seat totals (sum to {0}): '.format(GLA_ASSEMBLY_LIST_SEATS)
          + ' · '.join(
        f'{y}: {list_seats_total.get(y, 0)}' for y in present_years
    ))


if __name__ == '__main__':
    main()
