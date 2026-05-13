"""Fetch the 16 Senedd constituency boundary polygons from DataMapWales,
reproject + simplify to match data/ward_geoms.json's coordinate space, and
emit data/senedd_geoms.json.

Sibling to scripts/09_fetch_ward_boundaries.py: the y-flip / simplification
recipe is mirrored so Senedd polygons land in the same SVG space as the
WD24 wards and can overlay them without a transform.

DataMapWales publishes the final-determination boundaries as a GeoServer
WFS layer (`geonode:senedd_final_2026`) keyed by constituency name in
properties.english_na. The endpoint returns coords already in BNG
(EPSG:27700), so no reprojection step is needed — only y-flipping into
the same SVG range as the ward paths.

Source: https://datamap.gov.wales/layers/geonode:senedd_final_2026

Idempotent: skips work if data/senedd_geoms.json already exists unless
--force is passed. The raw GeoJSON is cached at
data/source/senedd_final_2026.geojson (~8 MB).
"""
import argparse
import json
import re
import urllib.request
from pathlib import Path

import geopandas as gpd

from _senedd_constituencies import SENEDD_CONSTITUENCIES

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "senedd_geoms.json"
RAW_CACHE = SOURCE / "senedd_final_2026.geojson"

WFS_URL = (
    'https://datamap.gov.wales/geoserver/wfs?service=WFS&version=2.0.0'
    '&request=GetFeature&typeNames=geonode:senedd_final_2026'
    '&outputFormat=application/json'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

# Same simplification tolerance as 09's BOROUGH layer — Senedd constituencies
# are large polygons (each covers ~600 km²), so ward-level 50 m is overkill.
SIMPLIFY_TOLERANCE_M = 100


def fetch_geojson() -> dict:
    req = urllib.request.Request(WFS_URL, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """Same y-flip + integer-rounding recipe as scripts/09's polygon_to_path,
    duplicated here to avoid a cross-script import (09 is build-only and
    pulls in heavyweight geo deps regardless)."""
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


def read_gb_y_bounds() -> tuple[float, float]:
    """Discover the GB-wide BNG y bounds used by 09 by scanning the ward
    paths in data/ward_geoms.json. The y-flip in 09's polygon_to_path
    means svg_y_range numerically equals bng_y_range, so the min/max of
    integer y values across every ward path is exactly what 09's
    `polygon_to_path(poly, maxy, miny)` was called with."""
    with open(DATA / 'ward_geoms.json') as f:
        geoms = json.load(f)
    pattern = re.compile(r'[ML](-?\d+),(-?\d+)')
    ys: list[int] = []
    for w in geoms['wards'].values():
        ys.extend(int(m.group(2)) for m in pattern.finditer(w['path']))
    if not ys:
        raise RuntimeError("could not scan y bounds from ward_geoms.json — empty wards?")
    return float(min(ys)), float(max(ys))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true', help='Re-run even if outputs exist')
    args = ap.parse_args()

    if OUT.exists() and not args.force:
        print(f'{OUT.relative_to(ROOT)} exists — skipping. Use --force to rebuild.')
        return

    SOURCE.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    if RAW_CACHE.exists():
        print(f'1. {RAW_CACHE.relative_to(ROOT)} cached — reusing')
        with open(RAW_CACHE) as f:
            fc = json.load(f)
    else:
        print('1. Fetching Senedd 2026 boundary GeoJSON from DataMapWales WFS...')
        fc = fetch_geojson()
        with open(RAW_CACHE, 'w') as f:
            json.dump(fc, f)
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')

    if len(fc['features']) != 16:
        raise RuntimeError(
            f'expected 16 Senedd features, got {len(fc["features"])}'
        )

    print('2. Reading GB y bounds from ward_geoms.json so Senedd paths share '
          'the wards\' SVG coord space...')
    min_y, max_y = read_gb_y_bounds()
    print(f'   gb y-range = [{min_y:.0f}, {max_y:.0f}]')

    print('3. Loading, simplifying, emitting SVG paths...')
    gdf = gpd.GeoDataFrame.from_features(fc['features'], crs='EPSG:27700')
    # name → SENEDD_CONSTITUENCIES code lookup
    name_to_code = {n: c for (c, n, _t) in SENEDD_CONSTITUENCIES}

    constituencies: dict[str, dict] = {}
    for _, row in gdf.iterrows():
        name = row['english_na']
        code = name_to_code.get(name)
        if not code:
            print(f'  ! GeoJSON name {name!r} not in SENEDD_CONSTITUENCIES — skipping')
            continue
        simplified = row.geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
        constituencies[code] = {
            'path': polygon_to_path(simplified, max_y, min_y),
            'name': name,
        }

    out_data = {'constituencies': constituencies}
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    print(
        f'\nDone. wrote {len(constituencies)} Senedd constituencies · '
        f'{size_kb:.1f} KB → {OUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
