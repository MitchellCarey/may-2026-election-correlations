"""Fetch the 43 Police Force Area boundary polygons in legal effect at the
2024 PCC elections and emit data/pfa_geoms.json.

Sibling to scripts/21_fetch_pcon_geoms.py — same y-flip / shared-bounds
recipe so PFA paths share the SVG coord space with wards, boroughs, CEDs,
Holyrood SPCs, Senedd constituencies and PCONs.

Source: ``Police_Force_Areas_Dec_2024_EW_BGC`` on the ONS Open Geography
Portal. BGC = Generalised Clipped, native CRS EPSG:27700 (BNG) so no
reprojection needed. The layer contains all 43 PFAs (39 English + 4
Welsh territorial forces); 41 of them have elected PCCs — the Metropolitan
Police Service (E23000001) and City of London Police (E23000034) are
filtered out at render time in 07d because they don't have elected PCC
roles (London uses MOPAC / the City of London Corporation arrangement
instead). They're written here for completeness — a future MPS / CoLP
layer can reuse the same polygon set without a re-fetch.

Idempotent: skips work if data/pfa_geoms.json already exists unless
--force. Raw GeoJSON is cached at data/source/pfa_dec_2024.geojson
(~5 MB; 43 polygons at PFA scale).
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
OUT = DATA / "pfa_geoms.json"
RAW_CACHE = SOURCE / "pfa_dec_2024.geojson"

PFA_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'Police_Force_Areas_Dec_2024_EW_BGC/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

# Same tolerance as Senedd / PCON — PFAs are at the regional scale, 100 m
# is invisible on a ~700 px GB canvas.
SIMPLIFY_TOLERANCE_M = 100


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_pfa_geom() -> dict:
    """Page through the PFA_DEC_2024 BGC FeatureServer. Returns a GeoJSON
    FeatureCollection in EPSG:27700 (BNG)."""
    page_size = 1000
    offset = 0
    all_features: list = []
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'PFA24CD,PFA24NM',
            'returnGeometry':    'true',
            'outSR':             27700,
            'f':                 'geojson',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     'PFA24CD',
        }
        d = http_get(PFA_GEOM_ENDPOINT, params)
        if isinstance(d, dict) and d.get('error'):
            raise RuntimeError(f'PFA geometry query failed: {d["error"]}')
        feats = d.get('features', [])
        all_features.extend(feats)
        print(f'  geometry page offset={offset} → {len(feats)} PFAs '
              f'(running total {len(all_features)})')
        if not d.get('exceededTransferLimit') and len(feats) < page_size:
            break
        offset += len(feats)
        time.sleep(0.3)
    return {'type': 'FeatureCollection', 'features': all_features}


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """Same y-flip + integer-rounding recipe as scripts/09 / 16 / 21.
    Duplicated here to keep this script standalone."""
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
    in data/ward_geoms.json. Same approach as scripts/16 / 21."""
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
        print('1. Fetching PFA_DEC_2024 boundary GeoJSON from ONS BGC FeatureServer...')
        fc = fetch_pfa_geom()
        with open(RAW_CACHE, 'w') as f:
            json.dump(fc, f)
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')

    if len(fc['features']) != 43:
        raise RuntimeError(
            f'expected 43 PFA features, got {len(fc["features"])}'
        )

    print('2. Reading GB y bounds from ward_geoms.json so PFA paths share '
          'the wards\' SVG coord space...')
    min_y, max_y = read_gb_y_bounds()
    print(f'   gb y-range = [{min_y:.0f}, {max_y:.0f}]')

    print('3. Loading, simplifying, emitting SVG paths...')
    gdf = gpd.GeoDataFrame.from_features(fc['features'], crs='EPSG:27700')

    forces: dict[str, dict] = {}
    for _, row in gdf.iterrows():
        code = row['PFA24CD']
        name = row['PFA24NM']
        simplified = row.geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
        forces[code] = {
            'path': polygon_to_path(simplified, max_y, min_y),
            'name': name,
        }

    out_data = {'forces': forces}
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    print(
        f'\nDone. wrote {len(forces)} PFA polygons · '
        f'{size_kb:.1f} KB → {OUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
