"""Fetch the 650 Westminster constituency boundary polygons in legal effect
at the 2015 / 2017 / 2019 General Elections — i.e. the pre-July-2024
boundary set — and emit data/pcon_geoms_2010.json.

Sibling to scripts/21_fetch_pcon_geoms.py (which fetches the July-2024
boundary set into data/pcon_geoms.json). Same y-flip + shared-bounds
recipe so 2010-era PCON paths land in the same SVG coord space as wards,
boroughs, CEDs, Holyrood SPCs, Senedd constituencies, and 2024-era PCONs.

Source: PCON_DEC_2021_UK_BGC (Westminster Parliamentary Constituencies,
December 2021, Boundaries UK, Generalised Clipped) on the ONS Open
Geography Portal. The boundaries did not change between the 2010
Constituencies Order and the July 2024 review, so any post-2010 /
pre-2024 ONS snapshot describes the same 650-constituency geometry —
December 2021 is simply the latest snapshot. Field names PCON21CD /
PCON21NM; codes are identical to the May 2010 PCON10CD set for all 650
seats (verified via the May-2010 → July-2024 lookup at data.gov.uk).

Why this and not the July-2024 set: most of the 650 constituency codes
changed under the 2024 review (E14000530 Aldershot → E14001063 Aldershot
etc.), so only 5 codes overlap between the two sets. To paint era-
accurate boundaries on the GB Current slider, 07d swaps PCON_PATHS_2010
in for years < 2024 and PCON_PATHS for years >= 2024. Both sets get
written; era visibility toggles in paintAtYear at the slider's 2024
boundary.

All 650 polygons (E14/W07/S14/N06) are written to disk. The GB/NI scope
decision happens at render time in 07d so a future NI render needs no
re-fetch.

Idempotent: skips work if data/pcon_geoms_2010.json already exists unless
--force. Raw GeoJSON cached at data/source/pcon_dec_2021.geojson (~30 MB).
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
OUT = DATA / "pcon_geoms_2010.json"
RAW_CACHE = SOURCE / "pcon_dec_2021.geojson"

PCON_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'Westminster_Parliamentary_Constituencies_Dec_2021_UK_BGC_2022/'
    'FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

# Same tolerance as the July-2024 set — PCON seats are at the constituency
# scale, not the ward scale. 100 m is invisible on a ~700 px GB canvas.
SIMPLIFY_TOLERANCE_M = 100


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_pcon_geom() -> dict:
    """Page through the PCON_DEC_2021 BGC FeatureServer. Returns a GeoJSON
    FeatureCollection in EPSG:27700 (BNG)."""
    page_size = 1000
    offset = 0
    all_features: list = []
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'PCON21CD,PCON21NM',
            'returnGeometry':    'true',
            'outSR':             27700,
            'f':                 'geojson',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     'PCON21CD',
        }
        d = http_get(PCON_GEOM_ENDPOINT, params)
        if isinstance(d, dict) and d.get('error'):
            raise RuntimeError(f'PCON geometry query failed: {d["error"]}')
        feats = d.get('features', [])
        all_features.extend(feats)
        print(f'  geometry page offset={offset} → {len(feats)} PCONs '
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
        print('1. Fetching PCON_DEC_2021 boundary GeoJSON from ONS BGC FeatureServer...')
        fc = fetch_pcon_geom()
        with open(RAW_CACHE, 'w') as f:
            json.dump(fc, f)
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')

    if len(fc['features']) != 650:
        raise RuntimeError(
            f'expected 650 PCON features, got {len(fc["features"])}'
        )

    print('2. Reading GB y bounds from ward_geoms.json so PCON paths share '
          'the wards\' SVG coord space...')
    min_y, max_y = read_gb_y_bounds()
    print(f'   gb y-range = [{min_y:.0f}, {max_y:.0f}]')

    print('3. Loading, simplifying, emitting SVG paths...')
    gdf = gpd.GeoDataFrame.from_features(fc['features'], crs='EPSG:27700')

    constituencies: dict[str, dict] = {}
    for _, row in gdf.iterrows():
        code = row['PCON21CD']
        name = row['PCON21NM']
        simplified = row.geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
        constituencies[code] = {
            'path': polygon_to_path(simplified, max_y, min_y),
            'name': name,
        }

    out_data = {'constituencies': constituencies}
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    print(
        f'\nDone. wrote {len(constituencies)} PCON constituencies · '
        f'{size_kb:.1f} KB → {OUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
