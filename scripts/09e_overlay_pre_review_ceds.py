"""Overlay pre-review CED polygons for the GB Current historical slider.

Sibling of scripts/09c_overlay_lgbce_ceds.py. Where 09c REPLACES the CED25
entries for counties with a May 2026 LGBCE review (Norfolk, Essex, Suffolk)
with LGBCE post-review polygons, 09e produces a PARALLEL pre-review polygon
set under a new top-level key `ceds_pre_review` so the slider in 07d can
paint 2017/2021 results on era-appropriate boundaries (issue #69 Phase 1B).

Counties handled:
  - Norfolk / Essex / Suffolk: pre-2026-review boundaries elected in 2017+2021.
    Pulled from ONS CED_MAY_2025 (which still has pre-review boundaries here —
    that's the same snapshot 09c overrides).
  - Surrey CC: pre-abolition boundaries elected in 2017+2021. Pulled from
    CED_MAY_2025 (Surrey's abolition takes effect April 2027). 09e also REMOVES
    Surrey's CED25 entries from `ceds` so 07d's era logic can cleanly distinguish
    "show Surrey at year < 2026" via membership of `ceds_pre_review`.

PRE_ keys never collide with bare CED25CDs (`E25*`) or LGBCE_ keys.

Order matters: run 09b → 09c → 09e. Idempotent; skips work if every target
county already has pre-review entries unless --force.
"""
import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "ward_geoms.json"
RAW_CACHE = SOURCE / "ced_may_2025_en_bgc.geojson"
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

CED_SIMPLIFY_TOLERANCE_M = 50

CED_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'CED_MAY_2025_EN_BGC/FeatureServer/0/query'
)
CED_LU_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'WD25_LAD25_CTY25_CED25_EN_LU/FeatureServer/0/query'
)

# Counties whose 2017/2021 boundaries differ from the 2025/2026 set in
# `ceds` after 09c runs. Each row carries the friendly name (for log output
# and the resulting meta) and a flag controlling whether to strip the
# county's bare CED25CD entries from `ceds` after PRE_ keys are written.
# Norfolk/Essex/Suffolk: 09c already removed their CED25 entries, so no
# extra stripping is needed. Surrey: still in `ceds` today (no LGBCE review)
# but will be abolished after 7 May 2026, so we move its entries to the
# `ceds_pre_review` bucket and drop them from `ceds`.
TARGETS = [
    {'cty_code': 'E10000020', 'cty_name': 'Norfolk',  'strip_post': False},
    {'cty_code': 'E10000012', 'cty_name': 'Essex',    'strip_post': False},
    {'cty_code': 'E10000029', 'cty_name': 'Suffolk',  'strip_post': False},
    {'cty_code': 'E10000030', 'cty_name': 'Surrey',   'strip_post': True},
]


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_ced_geom() -> dict:
    page_size = 1000
    offset = 0
    all_features = []
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'CED25CD,CED25NM',
            'returnGeometry':    'true',
            'outSR':             27700,
            'f':                 'geojson',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     'CED25CD',
        }
        d = http_get(CED_GEOM_ENDPOINT, params)
        if isinstance(d, dict) and d.get('error'):
            raise RuntimeError(f'CED geometry query failed: {d["error"]}')
        feats = d.get('features', [])
        all_features.extend(feats)
        print(f'  geometry page offset={offset} → {len(feats)} CEDs '
              f'(running total {len(all_features)})')
        if not d.get('exceededTransferLimit') and len(feats) < page_size:
            break
        offset += len(feats)
        time.sleep(0.3)
    return {'type': 'FeatureCollection', 'features': all_features}


def fetch_ced_county_lookup() -> dict:
    """Return {CED25CD: CTY25CD} so we can filter geometry by parent county."""
    page_size = 2000
    offset = 0
    ced_to_cty: dict[str, str] = {}
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'CED25CD,CTY25CD',
            'returnGeometry':    'false',
            'f':                 'json',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
        }
        d = http_get(CED_LU_ENDPOINT, params)
        if d.get('error'):
            raise RuntimeError(f'CED lookup query failed: {d["error"]}')
        feats = d.get('features', [])
        for f in feats:
            a = f['attributes']
            ced = a.get('CED25CD')
            cty = a.get('CTY25CD')
            if ced and cty and ced not in ced_to_cty:
                ced_to_cty[ced] = cty
        if not d.get('exceededTransferLimit'):
            break
        offset += len(feats)
        time.sleep(0.3)
    return ced_to_cty


def recover_yflip_basis(geoms: dict) -> tuple[int, int]:
    """Recover (min_y_bng, max_y_bng) from existing ward path coords.

    Same trick as scripts/09c — paths were y-flipped with
    `y_svg = max_y_bng - y_bng + min_y_bng`, so the range of y_svg
    integers equals the BNG y range.
    """
    coord_re = re.compile(r'[ML](-?\d+),(-?\d+)')
    min_y = None
    max_y = None
    for w in geoms.get('wards', {}).values():
        for m in coord_re.finditer(w['path']):
            y = int(m.group(2))
            if min_y is None or y < min_y:
                min_y = y
            if max_y is None or y > max_y:
                max_y = y
    if min_y is None or max_y is None:
        raise RuntimeError('no ward paths found in ward_geoms.json to recover y-flip basis')
    return min_y, max_y


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
    return s


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """SVG path with y-flip applied; same convention as scripts/09 / 09b / 09c."""
    parts = []
    geoms = poly.geoms if poly.geom_type == 'MultiPolygon' else [poly]
    for g in geoms:
        for ring in [g.exterior, *g.interiors]:
            coords = list(ring.coords)
            if len(coords) < 3:
                continue
            x0, y0 = coords[0][0], coords[0][1]
            parts.append(f'M{round(x0)},{round(max_y - y0 + min_y)}')
            for c in coords[1:]:
                x, y = c[0], c[1]
                parts.append(f'L{round(x)},{round(max_y - y + min_y)}')
            parts.append('Z')
    return ''.join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true',
                    help='Rebuild even if every target county already has pre-review entries')
    args = ap.parse_args()

    if not OUT.exists():
        raise SystemExit(
            f'{OUT.relative_to(ROOT)} not found — run scripts/09_fetch_ward_boundaries.py first.'
        )
    geoms = json.loads(OUT.read_text())
    if not geoms.get('ceds'):
        raise SystemExit(
            f'{OUT.relative_to(ROOT)} has no `ceds` key — run scripts/09b_fetch_ced_boundaries.py first.'
        )

    target_codes = {t['cty_code'] for t in TARGETS}
    existing_pre = geoms.get('ceds_pre_review', {})
    have_pre = {meta['cty'] for meta in existing_pre.values() if meta.get('cty') in target_codes}
    if target_codes <= have_pre and not args.force:
        print(f'{OUT.relative_to(ROOT)} already has pre-review CEDs for all '
              f'{len(target_codes)} target counties — skipping. Use --force to rebuild.')
        return

    SOURCE.mkdir(parents=True, exist_ok=True)

    print(f'1. Recovering y-flip basis from {len(geoms["wards"])} ward paths...')
    min_y, max_y = recover_yflip_basis(geoms)
    print(f'   BNG y range: [{min_y}, {max_y}]')

    if RAW_CACHE.exists():
        print(f'2. {RAW_CACHE.relative_to(ROOT)} cached — reusing')
        geom = json.loads(RAW_CACHE.read_text())
    else:
        print('2. Fetching CED25 geometry from ONS BGC FeatureServer...')
        geom = fetch_ced_geom()
        RAW_CACHE.write_text(json.dumps(geom))
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')
    print(f'   got {len(geom["features"])} CED polygons total')

    print('3. Fetching CED → CTY lookup to filter target counties...')
    ced_to_cty = fetch_ced_county_lookup()
    print(f'   got {len(ced_to_cty)} CED → county mappings')

    import geopandas as gpd  # lazy: same convention as 09b
    print('4. Loading + simplifying CED geometry (already in EPSG:27700)...')
    gdf = gpd.GeoDataFrame.from_features(geom['features'], crs='EPSG:27700')
    gdf['cty'] = gdf['CED25CD'].map(ced_to_cty)
    target_gdf = gdf[gdf['cty'].isin(target_codes)].copy()
    target_gdf['geom_s'] = target_gdf.geometry.simplify(
        CED_SIMPLIFY_TOLERANCE_M, preserve_topology=True
    )
    print(f'   filtered to {len(target_gdf)} CEDs across {len(target_codes)} target counties')

    print('5. Emitting PRE_ entries...')
    cty_name_by_code = {t['cty_code']: t['cty_name'] for t in TARGETS}
    pre_entries: dict[str, dict] = {}
    per_cty_counts: dict[str, int] = {}
    for _, row in target_gdf.iterrows():
        name = (row['CED25NM'] or '').strip()
        cty = row['cty']
        if not name or not cty:
            continue
        key = f'PRE_{cty}_{slugify(name)}'
        pre_entries[key] = {
            'path':     polygon_to_path(row['geom_s'], max_y, min_y),
            'name':     name,
            'cty':      cty,
            'cty_name': cty_name_by_code.get(cty, cty),
            # Cross-reference the bare CED25CD so 04e can use it as a join
            # tiebreaker when name-normalisation fails. Source: ONS lookup.
            'ced25cd':  row['CED25CD'],
        }
        per_cty_counts[cty] = per_cty_counts.get(cty, 0) + 1
    for t in TARGETS:
        print(f'   {t["cty_name"]:>10} ({t["cty_code"]}) → '
              f'{per_cty_counts.get(t["cty_code"], 0)} pre-review divisions')

    print('6. Stripping `ceds` entries for counties that have no post-2026 contest...')
    strip_codes = {t['cty_code'] for t in TARGETS if t['strip_post']}
    if strip_codes:
        old_ceds = geoms['ceds']
        kept = {
            code: meta for code, meta in old_ceds.items()
            if meta.get('cty') not in strip_codes
        }
        removed = len(old_ceds) - len(kept)
        geoms['ceds'] = kept
        print(f'   removed {removed} `ceds` entries for: {sorted(strip_codes)}')
        print(f'   ceds count: {len(old_ceds)} → {len(kept)}')
    else:
        print('   nothing to strip (Norfolk/Essex/Suffolk handled by 09c)')

    geoms['ceds_pre_review'] = pre_entries
    OUT.write_text(json.dumps(geoms, separators=(',', ':')))
    print(f'\nDone. {OUT.relative_to(ROOT)} carries {len(pre_entries)} '
          f'`ceds_pre_review` entries across {len(target_codes)} counties.')


if __name__ == '__main__':
    main()
