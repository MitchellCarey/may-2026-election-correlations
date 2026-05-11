"""Fetch and pre-process ONS WD24 ward boundaries for the 10 GM boroughs.

One-off, idempotent. Skips work if data/ward_geoms.json already exists
unless --force is passed. Mirrors the pattern in scripts/00_fetch_prior_winners.py.

Pipeline:
  1. Query WD24_LAD24_UK_LU on the ONS Open Geography Portal for the 10 GM
     LAD24 codes (E08000001-E08000010) → 215 (WD24CD, LAD24CD) tuples.
  2. Fetch geometry for those 215 wards from Wards_May_2024_Boundaries_UK_BGC
     (BGC = Generalised, Clipped — small enough to ship). Cached as raw
     GeoJSON in data/source/wd_may_2024_uk_bgc_gm.geojson; subsequent runs
     skip the network call.
  3. Reproject WGS84 → British National Grid (EPSG:27700). Web Mercator
     distorts UK shapes badly at this latitude, so BNG is the right call.
  4. Simplify each ward at 50 m tolerance (fine for a ~50 km canvas
     displayed at 340-700 px wide).
  5. Convert each polygon to an SVG path string. Y-axis is flipped at write
     time so SVG's downward-y matches BNG's northward-y — the renderer can
     drop the path strings straight into <path d="..."> with no transform.
  6. Dissolve wards by LAD24CD and emit borough outlines too (looser
     simplification — these are decorative).
  7. Write data/ward_geoms.json:
       {"viewBox": [minx, miny, width, height],
        "wards":    {WD24CD: {"path": "M...Z", "name": "...", "lad": "E08..."}},
        "boroughs": {LAD24CD: {"path": "M...Z", "name": "..."}}}
     The names/LAD codes let 07c join the results data (which is keyed by
     borough+ward name) to the geometry without a second network call.

Build-only — geopandas/shapely/pyproj are not needed at runtime; the deployed
artifact is just docs/map.html plus the small JSON file this writes.
"""
import argparse
import gzip
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "ward_geoms.json"
RAW_CACHE = SOURCE / "wd_may_2024_uk_bgc_gm.geojson"

GM_LAD_CODES = [
    'E08000001', 'E08000002', 'E08000003', 'E08000004', 'E08000005',
    'E08000006', 'E08000007', 'E08000008', 'E08000009', 'E08000010',
]

# Open Geography Portal FeatureServer endpoints. Layer names confirmed against
# the public /rest/services index — these are the canonical names ONS publishes.
LU_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'WD24_LAD24_UK_LU/FeatureServer/0/query'
)
GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'Wards_May_2024_Boundaries_UK_BGC/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

WARD_SIMPLIFY_TOLERANCE_M = 50
BOROUGH_SIMPLIFY_TOLERANCE_M = 100


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_lookup() -> dict:
    """Return {WD24CD: {name, lad, borough}} for all 215 GM wards."""
    in_list = ','.join(f"'{c}'" for c in GM_LAD_CODES)
    params = {
        'where':              f'LAD24CD IN ({in_list})',
        'outFields':          'WD24CD,WD24NM,LAD24CD,LAD24NM',
        'returnGeometry':     'false',
        'f':                  'json',
        'resultRecordCount':  2000,
    }
    d = http_get(LU_ENDPOINT, params)
    if d.get('error'):
        raise RuntimeError(f'lookup query failed: {d["error"]}')
    if d.get('exceededTransferLimit'):
        raise RuntimeError('lookup query hit transfer limit; not implemented')
    feats = d.get('features', [])
    return {
        f['attributes']['WD24CD']: {
            'name':    f['attributes']['WD24NM'],
            'lad':     f['attributes']['LAD24CD'],
            'borough': f['attributes']['LAD24NM'],
        }
        for f in feats
    }


def fetch_geometry(wd_codes: list[str]) -> dict:
    """Fetch BGC geometry as GeoJSON for the given WD24 codes, chunked to keep
    each URL well within the GET length limit (~6 KB per request)."""
    chunk_size = 70
    all_features = []
    n_chunks = (len(wd_codes) - 1) // chunk_size + 1
    for i in range(0, len(wd_codes), chunk_size):
        chunk = wd_codes[i:i + chunk_size]
        in_list = ','.join(f"'{c}'" for c in chunk)
        params = {
            'where':              f'WD24CD IN ({in_list})',
            'outFields':          'WD24CD',
            'returnGeometry':     'true',
            'outSR':              4326,
            'f':                  'geojson',
            'resultRecordCount':  2000,
        }
        print(f'  geometry chunk {i // chunk_size + 1}/{n_chunks} ({len(chunk)} wards)...')
        d = http_get(GEOM_ENDPOINT, params)
        if d.get('error'):
            raise RuntimeError(f'geometry query failed: {d["error"]}')
        if d.get('exceededTransferLimit'):
            raise RuntimeError(f'chunk hit transfer limit (size {chunk_size}); reduce')
        all_features.extend(d.get('features', []))
        time.sleep(0.3)
    return {'type': 'FeatureCollection', 'features': all_features}


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """SVG path d-attribute for a (Multi)Polygon, with the y-axis flipped so
    SVG's downward-y aligns with BNG's northward-y. Coords are rounded to
    integer metres — sub-metre precision is wasted on a ~700 px canvas."""
    parts = []
    geoms = poly.geoms if poly.geom_type == 'MultiPolygon' else [poly]
    for g in geoms:
        for ring in [g.exterior, *g.interiors]:
            coords = list(ring.coords)
            if len(coords) < 3:
                continue
            x0, y0 = coords[0]
            parts.append(f'M{round(x0)},{round(max_y - y0 + min_y)}')
            for x, y in coords[1:]:
                parts.append(f'L{round(x)},{round(max_y - y + min_y)}')
            parts.append('Z')
    return ''.join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true', help='Re-run even if outputs exist')
    args = ap.parse_args()

    if OUT.exists() and not args.force:
        print(f'{OUT.relative_to(ROOT)} exists — skipping. Use --force to rebuild.')
        return

    SOURCE.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    print('1. Fetching WD24 → LAD24 lookup for the 10 GM boroughs...')
    info_by_wd = fetch_lookup()
    wd_codes = sorted(info_by_wd.keys())
    print(f'   got {len(wd_codes)} wards')
    if len(wd_codes) != 215:
        print(f'   WARNING: expected 215 GM wards, lookup returned {len(wd_codes)}')

    if RAW_CACHE.exists() and not args.force:
        print(f'2. {RAW_CACHE.relative_to(ROOT)} cached — reusing')
        with open(RAW_CACHE) as f:
            geom = json.load(f)
    else:
        print('2. Fetching geometry from ONS BGC FeatureServer...')
        geom = fetch_geometry(wd_codes)
        with open(RAW_CACHE, 'w') as f:
            json.dump(geom, f)
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')
    if len(geom['features']) != len(wd_codes):
        raise RuntimeError(
            f'geometry fetch returned {len(geom["features"])} features, expected {len(wd_codes)}'
        )

    print('3. Loading, reprojecting (EPSG:4326 → 27700), simplifying ward geometry...')
    gdf = gpd.GeoDataFrame.from_features(geom['features'], crs='EPSG:4326')
    gdf = gdf.to_crs(27700)
    gdf['LAD24CD'] = gdf['WD24CD'].map(lambda c: info_by_wd[c]['lad'])
    gdf['geom_s'] = gdf.geometry.simplify(WARD_SIMPLIFY_TOLERANCE_M, preserve_topology=True)

    bounds = gdf['geom_s'].total_bounds  # [minx, miny, maxx, maxy]
    minx, miny, maxx, maxy = bounds
    pad = max(maxx - minx, maxy - miny) * 0.02
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad

    print('4. Emitting per-ward SVG paths (y-flipped to SVG coords)...')
    wards_out = {
        row['WD24CD']: {
            'path': polygon_to_path(row['geom_s'], maxy, miny),
            'name': info_by_wd[row['WD24CD']]['name'],
            'lad':  info_by_wd[row['WD24CD']]['lad'],
        }
        for _, row in gdf.iterrows()
    }

    print('5. Dissolving wards → borough outlines...')
    boroughs_out = {}
    for lad_code, group in gdf.groupby('LAD24CD'):
        merged = unary_union(group.geometry.tolist())
        merged = merged.simplify(BOROUGH_SIMPLIFY_TOLERANCE_M, preserve_topology=True)
        # Borough name is the same across all rows in the group; pull from any.
        borough_name = info_by_wd[group.iloc[0]['WD24CD']]['borough']
        boroughs_out[lad_code] = {
            'path': polygon_to_path(merged, maxy, miny),
            'name': borough_name,
        }

    out_data = {
        'viewBox': [round(minx), round(miny), round(maxx - minx), round(maxy - miny)],
        'wards':    wards_out,
        'boroughs': boroughs_out,
    }
    OUT.write_text(json.dumps(out_data, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    gz_kb = len(gzip.compress(OUT.read_bytes())) / 1024
    print(
        f'\nDone. wrote {len(wards_out)} wards + {len(boroughs_out)} boroughs '
        f'· {size_kb:.1f} KB (gzip {gz_kb:.1f} KB)'
    )
    print(f'   viewBox: {out_data["viewBox"]}')


if __name__ == '__main__':
    main()
