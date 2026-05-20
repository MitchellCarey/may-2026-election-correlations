"""Fetch the Greater London region polygon (E12000007) from the ONS Open
Geography Portal and emit data/gla_mayor_geom.json.

Sibling to scripts/21_fetch_pcon_geoms.py / scripts/16_fetch_senedd_geoms.py
— the y-flip + shared-bounds recipe is identical so the GLA Mayor polygon
lands in the same SVG coord space as wards, boroughs, CEDs, Holyrood SPCs,
Senedd constituencies and PCONs.

Source: Regions_December_2024_Boundaries_EN_BGC on the ONS Open Geography
Portal. BGC = Generalised Clipped (the variant every other ONS fetcher in
this repo uses — 09 / 16 / 16b / 21 / 21b). Native CRS EPSG:27700 (BNG) so
no reprojection is needed. The "London" region (E12000007) is coterminous
with the GLA's territory (32 London Boroughs + City of London), so one
ONS polygon = the entire mayoral overlay — no dissolution of LAD parts.

Idempotent: skips work if data/gla_mayor_geom.json already exists unless
--force. Raw GeoJSON for the single feature is cached at
data/source/region_london_dec_2024.geojson.
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
OUT = DATA / "gla_mayor_geom.json"
RAW_CACHE = SOURCE / "region_london_dec_2024.geojson"

REGION_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'Regions_December_2024_Boundaries_EN_BGC/FeatureServer/0/query'
)
LONDON_RGN_CODE = 'E12000007'
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

# Same tolerance as Senedd / PCON — the GLA outline is at regional scale,
# 100 m is invisible on a ~700 px GB canvas.
SIMPLIFY_TOLERANCE_M = 100


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_london_geom() -> dict:
    """Fetch the single London region feature from the Regions BFC layer
    in EPSG:27700."""
    params = {
        'where':          f"RGN24CD='{LONDON_RGN_CODE}'",
        'outFields':      'RGN24CD,RGN24NM',
        'returnGeometry': 'true',
        'outSR':          27700,
        'f':              'geojson',
    }
    d = http_get(REGION_GEOM_ENDPOINT, params)
    if isinstance(d, dict) and d.get('error'):
        raise RuntimeError(f'Regions geometry query failed: {d["error"]}')
    return d


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """Same y-flip + integer-rounding recipe as scripts/09 / 16 / 21."""
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
    data/ward_geoms.json. Same approach as scripts/16 / 21."""
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
        print(f'1. Fetching London region (RGN24CD={LONDON_RGN_CODE}) BGC boundary GeoJSON from ONS...')
        fc = fetch_london_geom()
        with open(RAW_CACHE, 'w') as f:
            json.dump(fc, f)
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')

    if len(fc['features']) != 1:
        raise RuntimeError(
            f'expected 1 London region feature, got {len(fc["features"])}'
        )

    print('2. Reading GB y bounds from ward_geoms.json so the GLA polygon '
          'shares the wards\' SVG coord space...')
    min_y, max_y = read_gb_y_bounds()
    print(f'   gb y-range = [{min_y:.0f}, {max_y:.0f}]')

    print('3. Loading, simplifying, emitting SVG path...')
    gdf = gpd.GeoDataFrame.from_features(fc['features'], crs='EPSG:27700')

    regions: dict[str, dict] = {}
    for _, row in gdf.iterrows():
        code = row['RGN24CD']
        name = row['RGN24NM']
        simplified = row.geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
        regions[code] = {
            'path': polygon_to_path(simplified, max_y, min_y),
            'name': name,
        }

    out_data = {'regions': regions}
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    print(
        f'\nDone. wrote {len(regions)} region polygon (London) · '
        f'{size_kb:.1f} KB → {OUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
