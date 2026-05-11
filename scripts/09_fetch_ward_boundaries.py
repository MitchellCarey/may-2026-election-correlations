"""Fetch and pre-process ONS WD24 ward boundaries for Great Britain.

One-off, idempotent. Skips work if data/ward_geoms.json already exists
unless --force is passed. Mirrors the pattern in scripts/00_fetch_prior_winners.py.

Pipeline:
  1. Query WD24_LAD24_UK_LU on the ONS Open Geography Portal for every ward
     in Great Britain (i.e. excluding Northern Ireland, where WD24CD starts
     with N09) → ~8,000 (WD24CD, LAD24CD) tuples, paginated.
  2. Fetch geometry for those wards from Wards_May_2024_Boundaries_UK_BGC
     (BGC = Generalised, Clipped — small enough to ship). Cached as raw
     GeoJSON in data/source/wd_may_2024_uk_bgc_gb.geojson; subsequent runs
     skip the network call. The cache is ~50 MB so it is gitignored.
  3. Reproject WGS84 → British National Grid (EPSG:27700). Web Mercator
     distorts UK shapes badly at this latitude, so BNG is the right call.
  4. Simplify each ward at 50 m tolerance (fine for any region from a
     ~50 km GM canvas up to a ~1,500 km GB canvas).
  5. Convert each polygon to an SVG path string. Y-axis is flipped at write
     time so SVG's downward-y matches BNG's northward-y — the renderer can
     drop the path strings straight into <path d="..."> with no transform.
     All paths share one global (GB) coordinate system so the same path
     data is reused across every region's viewBox.
  6. Dissolve wards by LAD24CD and emit per-council outlines too (looser
     simplification — these are decorative).
  7. Compute one viewBox per region (gm, gb) from each region's bounds in
     the shared SVG coordinate system, with a 2% pad.
  8. Write data/ward_geoms.json:
       {"viewBoxes": {"gm": [minx, miny, w, h], "gb": [...]},
        "wards":     {WD24CD: {"path": "M...Z", "name": "...", "lad": "E08..."}},
        "boroughs":  {LAD24CD: {"path": "M...Z", "name": "..."}}}
     The names/LAD codes let 07c join the results data (which is keyed by
     borough+ward name) to the geometry without a second network call.

Build-only — geopandas/shapely/pyproj are not needed at runtime; the deployed
artifact is just docs/map.html (and docs/uk/map.html) plus the JSON file
this writes.
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

from _councils import lad_codes_for

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "ward_geoms.json"
RAW_CACHE = SOURCE / "wd_may_2024_uk_bgc_gb.geojson"

REGIONS = ["gm", "gb"]

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

# Northern Ireland WD codes start with N09; GB = UK minus NI.
GB_WHERE = "WD24CD NOT LIKE 'N09%'"


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_lookup() -> dict:
    """Return {WD24CD: {name, lad, borough}} for every GB ward, paginating
    the lookup query (the WD24_LAD24_UK_LU layer caps each request at
    1000 rows; GB has ~8000)."""
    page_size = 1000
    offset = 0
    info_by_wd = {}
    while True:
        params = {
            'where':             GB_WHERE,
            'outFields':         'WD24CD,WD24NM,LAD24CD,LAD24NM',
            'returnGeometry':    'false',
            'f':                 'json',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     'WD24CD',
        }
        d = http_get(LU_ENDPOINT, params)
        if d.get('error'):
            raise RuntimeError(f'lookup query failed: {d["error"]}')
        feats = d.get('features', [])
        for f in feats:
            a = f['attributes']
            info_by_wd[a['WD24CD']] = {
                'name':    a['WD24NM'],
                'lad':     a['LAD24CD'],
                'borough': a['LAD24NM'],
            }
        print(f'  lookup page offset={offset} → {len(feats)} rows '
              f'(running total {len(info_by_wd)})')
        # `exceededTransferLimit` is the authoritative "more rows exist"
        # signal — the server can cap below page_size silently, so don't
        # also break on `len(feats) < page_size`.
        if not d.get('exceededTransferLimit'):
            break
        offset += len(feats)
        time.sleep(0.3)
    return info_by_wd


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


def viewbox_for(gdf_subset, global_maxy: float, global_miny: float) -> list[int]:
    """Compute the SVG-space viewBox for the given subset of wards, applying
    the same y-flip as the path coords and padding by 2% of the longer side."""
    minx, miny, maxx, maxy = gdf_subset['geom_s'].total_bounds
    svg_miny = global_maxy - maxy + global_miny
    svg_maxy = global_maxy - miny + global_miny
    width = maxx - minx
    height = svg_maxy - svg_miny
    pad = max(width, height) * 0.02
    return [
        round(minx - pad),
        round(svg_miny - pad),
        round(width + 2 * pad),
        round(height + 2 * pad),
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true', help='Re-run even if outputs exist')
    args = ap.parse_args()

    if OUT.exists() and not args.force:
        print(f'{OUT.relative_to(ROOT)} exists — skipping. Use --force to rebuild.')
        return

    SOURCE.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    print('1. Fetching WD24 → LAD24 lookup for GB (excluding NI)...')
    info_by_wd = fetch_lookup()
    wd_codes = sorted(info_by_wd.keys())
    print(f'   got {len(wd_codes)} wards across '
          f'{len({i["lad"] for i in info_by_wd.values()})} councils')

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

    # Single shared SVG coordinate system: y-flip uses the GB bounds, so every
    # path is in the same space and per-region viewBoxes just crop into it.
    minx, miny, maxx, maxy = gdf['geom_s'].total_bounds

    print('4. Emitting per-ward SVG paths (y-flipped to SVG coords)...')
    wards_out = {
        row['WD24CD']: {
            'path': polygon_to_path(row['geom_s'], maxy, miny),
            'name': info_by_wd[row['WD24CD']]['name'],
            'lad':  info_by_wd[row['WD24CD']]['lad'],
        }
        for _, row in gdf.iterrows()
    }

    print('5. Dissolving wards → council outlines...')
    boroughs_out = {}
    for lad_code, group in gdf.groupby('LAD24CD'):
        merged = unary_union(group.geometry.tolist())
        merged = merged.simplify(BOROUGH_SIMPLIFY_TOLERANCE_M, preserve_topology=True)
        borough_name = info_by_wd[group.iloc[0]['WD24CD']]['borough']
        boroughs_out[lad_code] = {
            'path': polygon_to_path(merged, maxy, miny),
            'name': borough_name,
        }

    print('6. Computing per-region viewBoxes...')
    view_boxes = {}
    for region in REGIONS:
        if region == 'gb':
            # GB shows the whole UK extent so the registered councils sit
            # in their real geographic context — boroughs we *don't* render
            # as data still appear as decorative outlines. The registry
            # subset would zoom in to wherever the 69 councils happen to
            # cluster.
            subset = gdf
        else:
            region_lads = lad_codes_for(region)
            subset = gdf[gdf['LAD24CD'].isin(region_lads)]
            if subset.empty:
                raise RuntimeError(
                    f'region {region!r} matched 0 wards in the fetched set — '
                    f'check councils.yaml lad_codes against ONS WD24 LAD24CDs'
                )
        view_boxes[region] = viewbox_for(subset, maxy, miny)
        print(f'   {region}: {len(subset)} wards · viewBox {view_boxes[region]}')

    out_data = {
        'viewBoxes': view_boxes,
        'wards':     wards_out,
        'boroughs':  boroughs_out,
    }
    OUT.write_text(json.dumps(out_data, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    gz_kb = len(gzip.compress(OUT.read_bytes())) / 1024
    print(
        f'\nDone. wrote {len(wards_out)} wards + {len(boroughs_out)} councils '
        f'· {size_kb:.1f} KB (gzip {gz_kb:.1f} KB)'
    )


if __name__ == '__main__':
    main()
