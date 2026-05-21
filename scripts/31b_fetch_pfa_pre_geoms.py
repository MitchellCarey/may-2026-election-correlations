"""Fetch the 43 Police Force Area boundary polygons under the earliest
ONS BGC vintage on the Open Geography Portal (December 2017) and emit
data/pfa_geoms_pre.json — the "pre" boundary set for the GB current
slider's PCC layer.

Sibling to scripts/31_fetch_pfa_geoms.py (which fetches the December
2024 set). PFA boundaries have been stable since 2007, so the 43 PFA
codes overlap 1:1 between the 2017 and 2024 sets — only the polygon
geometry differs (and in practice the two are within rounding noise
of each other). The era split is defensive against subtle ONS edits
we might miss; the renderer in 07d toggles between the two vintages
at the 2024 era boundary, mirroring the PCON pre/post split (#71).

Source: ``Police_Force_Areas_Dec_2017_EW_BGC_2022`` on the ONS Open
Geography Portal. Field names are lowercase here (``pfa17cd``,
``pfa17nm``) — they were normalised to upper-case from 2018 onwards.

Idempotent: skips work if data/pfa_geoms_pre.json already exists unless
--force. Raw GeoJSON cached at data/source/pfa_dec_2017.geojson.
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
OUT = DATA / "pfa_geoms_pre.json"
RAW_CACHE = SOURCE / "pfa_dec_2017.geojson"

PFA_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'Police_Force_Areas_Dec_2017_EW_BGC_2022/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

SIMPLIFY_TOLERANCE_M = 100


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_pfa_geom() -> dict:
    page_size = 1000
    offset = 0
    all_features: list = []
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'pfa17cd,pfa17nm',
            'returnGeometry':    'true',
            'outSR':             27700,
            'f':                 'geojson',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     'pfa17cd',
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
        print('1. Fetching PFA_DEC_2017 boundary GeoJSON from ONS BGC FeatureServer...')
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
        code = row['pfa17cd']
        name = row['pfa17nm']
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
