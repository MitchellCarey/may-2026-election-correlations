"""Overlay pre-review Holyrood polygons for the GB Current historical slider.

Sibling of scripts/09e_overlay_pre_review_ceds.py. Where 09d fetches the
SPC_MAY_2026 (post-review) 73-constituency set elected at the 7 May 2026
Scottish Parliament election, 09f fetches SPC_DEC_2022 — the 2014 73-
constituency set that was in legal effect for the 2016 and 2021 elections.

The 2026 review (Boundaries Commission for Scotland's First Review of
Scottish Parliament Boundaries) renamed/redrew roughly 20 of the 73 seats,
mostly in the central belt — so painting 2016/2021 winners on the 2026
polygons would misrepresent the contests. 09f produces a parallel polygon
set under `spcs_pre_review` keyed `PRE_<SPC22CD>` so 07d's era logic can
paint pre-review polygons at year < 2026 and the existing SPC26 polygons
at year >= 2026 (issue #69 Phase 1C / #74).

PRE_ keys never collide with bare SPC26CDs (both start `S16000` but use
disjoint numeric ranges — SPC22 codes pre-date the 2024 review).

Order matters: run 09 → 09d → 09f. Idempotent; skips work if
`spcs_pre_review` is already populated unless --force.
"""
import argparse
import gzip
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
RAW_CACHE = SOURCE / "spc_dec_2022_sc_bgc.geojson"
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

SPC_SIMPLIFY_TOLERANCE_M = 50

# The Dec 2022 snapshot reflects the 2014 73-constituency boundaries —
# unchanged from 2016 + 2021 elections. Internal layer name is
# SPC_DEC_2022_SC_BGC (visible via ?f=json on the service) but the public
# URL slug uses the long form `Scottish_Parliamentary_Constituencies_
# December_2022_Boundaries_SC_BGC` — the shorter slug 404s.
SPC_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'Scottish_Parliamentary_Constituencies_December_2022_Boundaries_SC_BGC/'
    'FeatureServer/0/query'
)


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_spc_geom() -> dict:
    """Page through the SPC22 BGC FeatureServer. Mirrors 09d.fetch_spc_geom
    but on the pre-review dataset and reading SPC22CD/SPC22NM attributes."""
    page_size = 1000
    offset = 0
    all_features = []
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'SPC22CD,SPC22NM',
            'returnGeometry':    'true',
            'outSR':             27700,
            'f':                 'geojson',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     'SPC22CD',
        }
        d = http_get(SPC_GEOM_ENDPOINT, params)
        if isinstance(d, dict) and d.get('error'):
            raise RuntimeError(f'SPC22 geometry query failed: {d["error"]}')
        feats = d.get('features', [])
        all_features.extend(feats)
        print(f'  geometry page offset={offset} → {len(feats)} SPCs '
              f'(running total {len(all_features)})')
        if not d.get('exceededTransferLimit') and len(feats) < page_size:
            break
        offset += len(feats)
        time.sleep(0.3)
    return {'type': 'FeatureCollection', 'features': all_features}


def recover_yflip_basis(geoms: dict) -> tuple[int, int]:
    """Recover (min_y_bng, max_y_bng) from existing ward path coords.

    Same trick as 09c/09e — paths were y-flipped with
    `y_svg = max_y_bng - y_bng + min_y_bng`, so the y_svg range equals
    the BNG y-range. Reused to keep 09f standalone (no need to redownload
    the 50 MB raw ward cache on fresh checkouts).
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


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """SVG path with y-flip applied; same convention as 09 / 09b / 09c / 09d / 09e."""
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
                    help='Rebuild even if `spcs_pre_review` already populated')
    args = ap.parse_args()

    if not OUT.exists():
        raise SystemExit(
            f'{OUT.relative_to(ROOT)} not found — run scripts/09_fetch_ward_boundaries.py first.'
        )
    geoms = json.loads(OUT.read_text())
    if not geoms.get('spcs'):
        raise SystemExit(
            f'{OUT.relative_to(ROOT)} has no `spcs` key — run scripts/09d_fetch_holyrood_boundaries.py first.'
        )
    if geoms.get('spcs_pre_review') and not args.force:
        n = len(geoms['spcs_pre_review'])
        print(f'{OUT.relative_to(ROOT)} already has `spcs_pre_review` '
              f'({n} polygons) — skipping. Use --force to rebuild.')
        return

    SOURCE.mkdir(parents=True, exist_ok=True)

    print(f'1. Recovering y-flip basis from {len(geoms["wards"])} ward paths...')
    min_y, max_y = recover_yflip_basis(geoms)
    print(f'   BNG y range: [{min_y}, {max_y}]')

    if RAW_CACHE.exists():
        print(f'2. {RAW_CACHE.relative_to(ROOT)} cached — reusing')
        geom = json.loads(RAW_CACHE.read_text())
    else:
        print('2. Fetching SPC22 geometry from ONS BGC FeatureServer...')
        geom = fetch_spc_geom()
        RAW_CACHE.write_text(json.dumps(geom))
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')
    print(f'   got {len(geom["features"])} SPC22 polygons')

    import geopandas as gpd  # lazy: same convention as 09b/09d/09e
    print('3. Loading + simplifying SPC22 geometry (already in EPSG:27700)...')
    gdf = gpd.GeoDataFrame.from_features(geom['features'], crs='EPSG:27700')
    gdf['geom_s'] = gdf.geometry.simplify(
        SPC_SIMPLIFY_TOLERANCE_M, preserve_topology=True
    )
    print(f'   simplified {len(gdf)} polygons at {SPC_SIMPLIFY_TOLERANCE_M} m tolerance')

    print('4. Emitting PRE_ entries...')
    pre_entries: dict[str, dict] = {}
    for _, row in gdf.iterrows():
        code = (row['SPC22CD'] or '').strip()
        name = (row['SPC22NM'] or '').strip()
        if not code or not name:
            continue
        key = f'PRE_{code}'
        pre_entries[key] = {
            'path':    polygon_to_path(row['geom_s'], max_y, min_y),
            'name':    name,
            'spc22cd': code,
        }

    geoms['spcs_pre_review'] = pre_entries
    OUT.write_text(json.dumps(geoms, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    gz_kb = len(gzip.compress(OUT.read_bytes())) / 1024
    print(f'\nDone. {OUT.relative_to(ROOT)} carries {len(pre_entries)} '
          f'`spcs_pre_review` entries · total file {size_kb:.1f} KB '
          f'(gzip {gz_kb:.1f} KB)')


if __name__ == '__main__':
    main()
