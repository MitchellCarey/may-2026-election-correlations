"""Build the per-SPC per-year history dataset for the GB Current map page's
Holyrood time-slider repaint (issue #69 Phase 1C / #74).

Sibling of scripts/04e_build_ced_history.py — same three-pass shape, but
keyed by Holyrood polygon (current SPC26CDs from ward_geoms.json `spcs`
and pre-review PRE_<SPC22CD>s from `spcs_pre_review`).

Sources, per (polygon, year) precedence (later passes win on tie):
  1. data/source/holyrood_official_<year>.csv — hand-curated fallback for
     Wikipedia content gaps. Schema: spc22cd,year,party,candidate,source,url,note
  2. data/holyrood_history_raw.json — Wikipedia per-constituency
     extractions for 2016 + 2021 (output of scripts/18b).
  3. data/holyrood_winners.json — Wikipedia 2026 results (output of
     scripts/18). Routes to current SPC26CD polygons.

Polygon era matching (which years a polygon can accept):
  - bare S16000*** in `spcs` (SPC26 codes S16000151-S16000223) → year 2026.
  - PRE_S16000*** in `spcs_pre_review` (SPC22 codes S16000074-S16000150)
    → year < 2026.

Output: data/holyrood_history.json with schema (mirrors ced_history.json):
  { "years": [2016, 2021, 2026],
    "spcs": { "<polygon_key>": {
        "name":    "Aberdeen Central",
        "region":  "North East Scotland",
        "history": [ {y, w, src, url, candidate?} ... ascending by year ] } } }

Determinism: sort_keys=True on json.dump, per-SPC history ascending by year.
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
from _holyrood_constituencies import HOLYROOD_22

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"

# Holyrood-tier year stops the slider exposes for the SPC layer. Scottish
# Parliament elections run on a 5-year cycle (2016, 2021, 2026 for the
# slider's depth window; pre-2016 contests are out of scope for Phase 1C).
SLIDER_YEARS = [2016, 2021, 2026]

# Source rank — higher number wins. Each pass overwrites earlier on tie so
# 04f's last word lands in history. Mirrors 04e's per-polygon dedup.
SOURCE_RANK = {'wiki': 0, 'official': 1}

WIKI_URL_2026 = 'https://en.wikipedia.org/wiki/Results_of_the_2026_Scottish_Parliament_election'


def wikipedia_url(title: str) -> str:
    """Same convention as 04d.wikipedia_url / 04e.wikipedia_url."""
    return f'https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(" ", "_"), safe="_,()/")}'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.parse_args()

    with open(DATA / 'ward_geoms.json') as f:
        geoms = json.load(f)
    spcs_current = geoms.get('spcs') or {}
    spcs_pre = geoms.get('spcs_pre_review') or {}
    if not spcs_current:
        raise SystemExit('ward_geoms.json has no `spcs` — run 09d first.')
    if not spcs_pre:
        raise SystemExit('ward_geoms.json has no `spcs_pre_review` — run 09f first.')

    # Build SPC22 → metadata index (name + region + wiki article URL).
    reg_meta_by_spc22 = {
        code: {
            'name':   name,
            'region': region,
            'url':    wikipedia_url(wiki_title),
        }
        for code, name, region, wiki_title in HOLYROOD_22
    }

    # 2026 SPCs lack a per-constituency wiki article in our registry; the
    # region is recoverable by matching name via the SPC22 set where the
    # 2026 review didn't rename, but for the 20-odd renamed seats we leave
    # `region` as the literal SPC26NM area name where the 2014→2026 mapping
    # isn't 1:1. Tooltip falls back to the constituency name + year + party.
    # The 2026 region is also derivable from the SPC26_SPR26 ONS lookup —
    # adding that pull would be premature for the Phase 1C slider which
    # only needs region labels for the tooltip on the pre-review polygons.
    # (PRE_ polygons drive 2016/2021 reads where region is most informative.)

    history: dict[str, dict[int, dict]] = defaultdict(dict)
    polygon_meta: dict[str, dict] = {}

    def upsert(polygon_key: str, year: int, entry: dict, src_tag: str):
        prev = history[polygon_key].get(year)
        if prev and SOURCE_RANK.get(src_tag, -1) <= SOURCE_RANK.get(prev.get('src', ''), -1):
            return
        history[polygon_key][year] = {**entry, 'src': src_tag}

    # --- Polygon meta — pre-review polygons ---
    for key, meta in spcs_pre.items():
        spc22cd = meta.get('spc22cd') or key.removeprefix('PRE_')
        reg = reg_meta_by_spc22.get(spc22cd, {})
        polygon_meta[key] = {
            'name':   meta.get('name') or reg.get('name', ''),
            'region': reg.get('region', ''),
        }

    # --- Polygon meta — current (2026) polygons ---
    for key, meta in spcs_current.items():
        polygon_meta[key] = {
            'name':   meta.get('name', ''),
            'region': '',  # filled below from 2026 record if available
        }

    # --- Pass 1: Wikipedia 2016 + 2021 per-constituency extractions ---
    raw_path = DATA / 'holyrood_history_raw.json'
    raw_records = json.loads(raw_path.read_text()) if raw_path.exists() else []
    pass1_added = 0
    for rec in raw_records:
        spc22cd = rec['spc22cd']
        year = rec['year']
        if year not in SLIDER_YEARS:
            continue
        polygon_key = f'PRE_{spc22cd}'
        if polygon_key not in spcs_pre:
            print(f'  WARN: raw record for {spc22cd} {year} has no pre-review polygon',
                  file=sys.stderr)
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
    winners_path = DATA / 'holyrood_winners.json'
    winners = json.loads(winners_path.read_text()) if winners_path.exists() else []
    pass2_added = 0
    for rec in winners:
        spc26cd = rec['spc']
        if spc26cd not in spcs_current:
            print(f'  WARN: 2026 winner {spc26cd} has no current polygon',
                  file=sys.stderr)
            continue
        if not rec.get('winner'):
            continue
        upsert(spc26cd, 2026, {
            'y':         2026,
            'w':         rec['winner'],
            'url':       WIKI_URL_2026,
            'candidate': None,
        }, 'wiki')
        pass2_added += 1

    # --- Pass 3: Hand-curated holyrood_official_<year>.csv fallbacks ---
    # Schema: spc22cd,year,party,candidate,source,url,note
    pass3_added = 0
    for path in sorted(SOURCE.glob('holyrood_official_*.csv')):
        m = re.match(r'holyrood_official_(\d{4})\.csv$', path.name)
        if not m:
            continue
        year = int(m.group(1))
        if year not in SLIDER_YEARS:
            continue
        with path.open(newline='') as f:
            for row in csv.DictReader(f):
                spc22cd = (row.get('spc22cd') or '').strip()
                party = (row.get('party') or '').strip()
                if not spc22cd or not party:
                    continue
                polygon_key = f'PRE_{spc22cd}' if year < 2026 else spc22cd
                pool = spcs_pre if year < 2026 else spcs_current
                if polygon_key not in pool:
                    print(f'  WARN: official row {spc22cd} {year} has no '
                          f'{"pre-review" if year < 2026 else "current"} polygon',
                          file=sys.stderr)
                    continue
                upsert(polygon_key, year, {
                    'y':         year,
                    'w':         party,
                    'url':       (row.get('url') or '').strip(),
                    'candidate': (row.get('candidate') or '').strip() or None,
                }, 'official')
                pass3_added += 1

    # --- Output assembly ---
    out_spcs: dict[str, dict] = {}
    for polygon_key, per_year in history.items():
        meta = polygon_meta.get(polygon_key, {})
        entries = []
        for entry in sorted(per_year.values(), key=lambda e: e['y']):
            clean = {'y': entry['y'], 'w': entry['w'],
                     'src': entry['src'], 'url': entry.get('url', '')}
            if entry.get('candidate'):
                clean['candidate'] = entry['candidate']
            entries.append(clean)
        out_spcs[polygon_key] = {
            'name':    meta.get('name', ''),
            'region':  meta.get('region', ''),
            'history': entries,
        }

    all_years_in_data = {e['y'] for per_year in history.values()
                           for e in per_year.values()}
    present_years = sorted(set(SLIDER_YEARS) & all_years_in_data)

    out = {'years': present_years, 'spcs': out_spcs}
    with open(DATA / 'holyrood_history.json', 'w') as f:
        json.dump(out, f, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

    total_polys = len(out_spcs)
    total_spc_years = sum(len(s['history']) for s in out_spcs.values())
    per_year_coverage: dict[int, int] = defaultdict(int)
    for s in out_spcs.values():
        for e in s['history']:
            per_year_coverage[e['y']] += 1
    print(f'Wrote holyrood_history.json — {total_polys} SPC polygons, '
          f'{len(present_years)} year stops, {total_spc_years:,} SPC-years')
    print(f'  passes: 1={pass1_added} (wiki 2016+2021), '
          f'2={pass2_added} (wiki 2026), 3={pass3_added} (hand-curated)')
    print('  per-year coverage: ' + ' · '.join(
        f'{y}: {per_year_coverage.get(y, 0)}' for y in present_years
    ))

    # Per-region summary (mirrors 04e's per-county block).
    per_region_polys: dict[str, int] = defaultdict(int)
    per_region_grey: dict[str, int] = defaultdict(int)
    for polygon_key, s in out_spcs.items():
        if not polygon_key.startswith('PRE_'):
            continue
        reg = s.get('region') or '(unknown)'
        per_region_polys[reg] += 1
        if not any(e['y'] in (2016, 2021) for e in s['history']):
            per_region_grey[reg] += 1
    if per_region_polys:
        print('  per-region pre-review coverage (polygons / with-history):')
        for reg in sorted(per_region_polys):
            n = per_region_polys[reg]
            grey = per_region_grey[reg]
            ok = n - grey
            flag = '' if grey == 0 else f'  ← {grey} grey'
            print(f'    {reg:>24}: {ok:2d} / {n:2d}{flag}')


if __name__ == '__main__':
    main()
