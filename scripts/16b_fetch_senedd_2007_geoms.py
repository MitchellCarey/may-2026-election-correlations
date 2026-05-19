"""Fetch the 40 pre-2026 Welsh Assembly Constituency (NAWC21) boundary
polygons from ONS, simplify + y-flip into the GB SVG coord space, and
emit data/senedd_geoms_2007.json (issue #69 Phase 1D / #72).

Sibling of scripts/16_fetch_senedd_geoms.py — the 2026 16-seat layout
comes from DataMapWales (`geonode:senedd_final_2026`). The 2007–2021
40-seat layout lives on the ONS Open Geography Portal under
`NAWC_DEC_2021_WA_BGC_V3` (the BGC = Generalised Clipped variant,
~1 MB total for all 40 polygons; the BFC / Full variant is ~10× larger
without visible benefit at GB-wide scale).

The 2021 snapshot date matches the boundary set legally in effect at
the 2016 + 2021 elections — Welsh Assembly Constituencies were last
reviewed in 2006, so the December 2021 polygons are still the original
2007 boundaries. (`Senedd Cymru` is the renamed institution; the
"Welsh Assembly Constituency" terminology in the layer name reflects
the pre-2020 institutional name preserved by ONS for continuity.)

Output: data/senedd_geoms_2007.json — same schema as senedd_geoms.json:
  {"constituencies": {
    "W09000001": {"path": "M...", "name": "Ynys Môn"},
    ... 40 entries ...
  }}

Y-flip recipe: same as 16 — read GB y-bounds from ward_geoms.json so
the new polygons share the SVG coord space with the WD24 wards, the
2026 Senedd, CEDs, Holyrood, PCONs, and Surrey. Simplification: 100 m
(matches 16; Welsh constituencies are large enough that ward-level
50 m is overkill).

Idempotent: skips work if data/senedd_geoms_2007.json already exists
unless --force is passed. The raw GeoJSON is cached at
data/source/nawc_dec_2021_wa_bgc_v3.geojson.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _senedd_constituencies_2007 import SENEDD_CONSTITUENCIES_2007

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "senedd_geoms_2007.json"
RAW_CACHE = SOURCE / "nawc_dec_2021_wa_bgc_v3.geojson"

ONS_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'NAWC_DEC_2021_WA_BGC_V3/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

SIMPLIFY_TOLERANCE_M = 100


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_nawc_geom() -> dict:
    """Page through the NAWC21 BGC FeatureServer. Mirrors 09d/09f's pager."""
    page_size = 1000
    offset = 0
    all_features = []
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'NAWC21CD,NAWC21NM',
            'returnGeometry':    'true',
            'outSR':             27700,
            'f':                 'geojson',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     'NAWC21CD',
        }
        d = http_get(ONS_ENDPOINT, params)
        if isinstance(d, dict) and d.get('error'):
            raise RuntimeError(f'NAWC21 geometry query failed: {d["error"]}')
        feats = d.get('features', [])
        all_features.extend(feats)
        print(f'  geometry page offset={offset} → {len(feats)} constituencies '
              f'(running total {len(all_features)})')
        if not d.get('exceededTransferLimit') and len(feats) < page_size:
            break
        offset += len(feats)
        time.sleep(0.3)
    return {'type': 'FeatureCollection', 'features': all_features}


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """SVG path with y-flip applied; same convention as 09 / 16 / 09f."""
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
    paths in ward_geoms.json. Mirrors 16.read_gb_y_bounds."""
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
        print('1. Fetching NAWC21 boundary GeoJSON from ONS BGC FeatureServer...')
        fc = fetch_nawc_geom()
        with open(RAW_CACHE, 'w') as f:
            json.dump(fc, f)
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')

    if len(fc['features']) != len(SENEDD_CONSTITUENCIES_2007):
        raise RuntimeError(
            f'expected {len(SENEDD_CONSTITUENCIES_2007)} NAWC21 features, '
            f'got {len(fc["features"])}'
        )

    print('2. Reading GB y bounds from ward_geoms.json so NAWC21 paths share '
          'the wards\' SVG coord space...')
    min_y, max_y = read_gb_y_bounds()
    print(f'   gb y-range = [{min_y:.0f}, {max_y:.0f}]')

    print(f'3. Loading + simplifying NAWC21 geometry '
          f'(EPSG:27700, {SIMPLIFY_TOLERANCE_M} m tolerance)...')
    gdf = gpd.GeoDataFrame.from_features(fc['features'], crs='EPSG:27700')
    gdf['geom_s'] = gdf.geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)

    # Index registry codes for sanity-check cross-walk.
    registry_codes = {c for c, *_ in SENEDD_CONSTITUENCIES_2007}

    constituencies: dict[str, dict] = {}
    unknown: list[str] = []
    for _, row in gdf.iterrows():
        code = (row['NAWC21CD'] or '').strip()
        name = (row['NAWC21NM'] or '').strip()
        if code not in registry_codes:
            unknown.append(f'{code} · {name}')
            continue
        constituencies[code] = {
            'path': polygon_to_path(row['geom_s'], max_y, min_y),
            'name': name,
        }

    missing = registry_codes - set(constituencies)
    if missing:
        for code in sorted(missing):
            print(f'  WARN: registry code {code} has no NAWC21 polygon',
                  file=sys.stderr)
    if unknown:
        for label in unknown:
            print(f'  WARN: NAWC21 polygon {label} not in registry — dropped',
                  file=sys.stderr)

    out_data = {'constituencies': constituencies}
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    print(
        f'\nDone. wrote {len(constituencies)} NAWC21 constituencies · '
        f'{size_kb:.1f} KB → {OUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
