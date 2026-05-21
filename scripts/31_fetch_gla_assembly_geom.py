"""Fetch the 14 London Assembly Constituency polygons (E32000001..E32000014)
from the ONS Open Geography Portal and emit data/gla_assembly_geom.json
(issue #89).

Sibling of scripts/28_fetch_gla_mayor_geom.py / scripts/21_fetch_pcon_geoms.py
— the y-flip + shared-bounds recipe is identical so the 14 LAC polygons
land in the same SVG coord space as wards, boroughs, CEDs, Holyrood SPCs,
Senedd constituencies, PCONs, the GLA Mayor polygon and EU referendum
LADs.

Source: London_Assembly_Constituencies_Dec_2017_EN_BGC_2022 on the ONS
Open Geography Portal. BGC = Generalised Clipped (the variant every other
ONS fetcher in this repo uses — 09 / 16 / 16b / 21 / 21b / 27 / 28).
LAC boundaries have been stable since 2000, so the December 2017
snapshot describes the geometry used at every Assembly election in the
slider window (2012 / 2016 / 2021 / 2024); the post-2017 LAC_*_NC
datasets (2018-2025) only carry names and codes, not geometry. Native
CRS EPSG:27700 (BNG) so no reprojection is needed.

Idempotent: skips work if data/gla_assembly_geom.json already exists
unless --force. Raw GeoJSON for the 14 features is cached at
data/source/lac_dec_2017.geojson.
"""
import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "gla_assembly_geom.json"
RAW_CACHE = SOURCE / "lac_dec_2017.geojson"

LAC_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'London_Assembly_Constituencies_Dec_2017_EN_BGC_2022/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

# LACs are small (each covers 2-4 London boroughs) but the GB canvas is
# huge, so 100 m matches the tolerance used by Senedd / PCON / GLA Mayor.
SIMPLIFY_TOLERANCE_M = 100


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_all_lac() -> dict:
    """Fetch all 14 LAC features in EPSG:27700."""
    params = {
        'where':          '1=1',
        'outFields':      'lac17cd,lac17nm',
        'returnGeometry': 'true',
        'outSR':          27700,
        'f':              'geojson',
    }
    d = http_get(LAC_GEOM_ENDPOINT, params)
    if isinstance(d, dict) and d.get('error'):
        raise RuntimeError(f'LAC geometry query failed: {d["error"]}')
    return d


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """Same y-flip + integer-rounding recipe as scripts/09 / 16 / 21 / 28."""
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
    """Discover the GB-wide BNG y bounds 09 used by scanning ward paths in
    data/ward_geoms.json. Same approach as scripts/16 / 21 / 28."""
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
        print(f'1. Fetching all 14 LAC BGC features from ONS...')
        fc = fetch_all_lac()
        with open(RAW_CACHE, 'w') as f:
            json.dump(fc, f)
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')

    if len(fc['features']) != 14:
        print(f'  ! expected 14 LAC features, got {len(fc["features"])}')

    print('2. Reading GB y bounds from ward_geoms.json so LAC polygons '
          'share the wards\' SVG coord space...')
    min_y, max_y = read_gb_y_bounds()
    print(f'   gb y-range = [{min_y:.0f}, {max_y:.0f}]')

    print('3. Loading, simplifying, emitting SVG paths...')
    gdf = gpd.GeoDataFrame.from_features(fc['features'], crs='EPSG:27700')

    constituencies: dict[str, dict] = {}
    for _, row in gdf.iterrows():
        code = row['lac17cd']
        name = row['lac17nm']
        simplified = row.geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
        constituencies[code] = {
            'path': polygon_to_path(simplified, max_y, min_y),
            'name': name,
        }

    out_data = {'constituencies': constituencies}
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    print(
        f'\nDone. wrote {len(constituencies)} LAC polygons · '
        f'{size_kb:.1f} KB → {OUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
