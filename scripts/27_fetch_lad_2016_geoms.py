"""Fetch the 380 LAD_Dec_2016 GB boundary polygons from the ONS Open
Geography Portal, simplify + y-flip into the shared GB SVG coord space,
and emit data/lad_geoms_2016.json.

Sibling to scripts/21b_fetch_pcon_2010_geoms.py — same recipe for a
vintage boundary set that doesn't share key space with any current layer.
The 23 June 2016 EU referendum was contested under 2016-era LADs;
Dorset/BCP, Buckinghamshire, N/W Northamptonshire, Cumberland/Westmorland
& Furness, Somerset and North Yorkshire all post-date the referendum, so
painting 2016 results on today's `boroughs` (dissolved from WD24 wards)
would smear historical results across reorganised authorities. The
December 2016 snapshot describes the LAD layout in legal effect on
referendum day — Welsh LADs were last reorganised in 1996, Scottish
councils have been stable since 1996, and English districts only began
their 2019→2025 reorganisation cycle three years after the referendum.

Source: LAD_Dec_2016_GB_BGC_2022 on the ONS Open Geography Portal.
BGC = Generalised Clipped, native CRS EPSG:27700 (BNG) so no reprojection
is needed — only y-flipping into the same SVG range as the ward paths.
The `_GB_` infix means NI is already excluded server-side; the layer
ships 380 features (326 E06/E07/E08/E09 + 22 W06 + 32 S12).

Idempotent: skips work if data/lad_geoms_2016.json already exists unless
--force is passed. The raw GeoJSON is cached at
data/source/lad_dec_2016_gb_bgc.geojson (~10 MB).
"""
import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "lad_geoms_2016.json"
RAW_CACHE = SOURCE / "lad_dec_2016_gb_bgc.geojson"

LAD_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'LAD_Dec_2016_GB_BGC_2022/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

# Same tolerance as borough / county / PCON / Senedd. LADs are at the
# council scale (median ~200 km²); 100 m simplification is invisible on
# a ~700 px GB canvas.
SIMPLIFY_TOLERANCE_M = 100


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_lad_geom() -> dict:
    """Page through the LAD_Dec_2016_GB_BGC_2022 FeatureServer. Returns a
    GeoJSON FeatureCollection in EPSG:27700 (BNG)."""
    page_size = 1000
    offset = 0
    all_features: list = []
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'LAD16CD,LAD16NM',
            'returnGeometry':    'true',
            'outSR':             27700,
            'f':                 'geojson',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     'LAD16CD',
        }
        d = http_get(LAD_GEOM_ENDPOINT, params)
        if isinstance(d, dict) and d.get('error'):
            raise RuntimeError(f'LAD geometry query failed: {d["error"]}')
        feats = d.get('features', [])
        all_features.extend(feats)
        print(f'  geometry page offset={offset} → {len(feats)} LADs '
              f'(running total {len(all_features)})')
        if not d.get('exceededTransferLimit') and len(feats) < page_size:
            break
        offset += len(feats)
        time.sleep(0.3)
    return {'type': 'FeatureCollection', 'features': all_features}


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """Same y-flip + integer-rounding recipe as scripts/09 / 16 / 21.
    Duplicated here to keep this script standalone (those carry the same
    function for the same reason — extracting to a shared helper is an
    optional cleanup, tracked nowhere)."""
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
    """Discover the GB-wide BNG y bounds used by 09 by scanning ward paths
    in data/ward_geoms.json. Same approach as scripts/16 / 21 / 24."""
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
        print('1. Fetching LAD_Dec_2016_GB_BGC_2022 from ONS BGC FeatureServer...')
        fc = fetch_lad_geom()
        with open(RAW_CACHE, 'w') as f:
            json.dump(fc, f)
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')

    n_feat = len(fc['features'])
    # GB LAD16 = 326 English + 22 Welsh + 32 Scottish = 380. The
    # _GB_ infix on the layer name excludes NI server-side.
    if n_feat != 380:
        print(f'  WARN: expected 380 GB LAD features, got {n_feat} — '
              f'continuing anyway (ONS may have added/removed a code)')

    print('2. Reading GB y bounds from ward_geoms.json so LAD paths share '
          'the wards\' SVG coord space...')
    min_y, max_y = read_gb_y_bounds()
    print(f'   gb y-range = [{min_y:.0f}, {max_y:.0f}]')

    print('3. Loading, simplifying, emitting SVG paths...')
    gdf = gpd.GeoDataFrame.from_features(fc['features'], crs='EPSG:27700')

    lads: dict[str, dict] = {}
    for _, row in gdf.iterrows():
        code = row['LAD16CD']
        name = row['LAD16NM']
        simplified = row.geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
        lads[code] = {
            'path': polygon_to_path(simplified, max_y, min_y),
            'name': name,
        }

    out_data = {'lads': lads}
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    print(
        f'\nDone. wrote {len(lads)} LAD16CD polygons · '
        f'{size_kb:.1f} KB → {OUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
