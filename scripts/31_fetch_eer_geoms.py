"""Fetch the 11 GB European Electoral Region (EER) polygons from the ONS
Open Geography Portal, simplify + y-flip into the shared GB SVG coord
space, and emit data/eer_geoms.json (issue #91).

Sibling to scripts/21_fetch_pcon_geoms.py / scripts/27_fetch_lad_2016_geoms.py
/ scripts/28_fetch_gla_mayor_geom.py — same recipe for an overlay layer
that ships its own polygon set sharing the GB SVG coord space derived
from ward_geoms.json.

Source: EER_Dec_2018_GCB_UK_2022 on the ONS Open Geography Portal. The
December 2018 snapshot is the boundary set in legal effect at both the
2014 and 2019 European Parliament elections (EERs were created in 1999
and unchanged until the UK left the EU on 31 January 2020), so a single
polygon set serves both contests — no PRE_/era logic needed, mirroring
the GLA Mayor overlay.

Native CRS is EPSG:27700 (BNG) so no reprojection is needed; we
y-flip into the same SVG range as the ward paths exactly like the
other GB overlays do. NI is filtered to keep parity with the
`gb` viewBox (which excludes NI) and with the PCON / Senedd /
Holyrood / Surrey / LAD-2016 layers that all filter NI at fetch
or render time. GB filter prefixes: E15* (English regions), S15*
(Scotland), W08* (Wales). NI's N07* prefix is dropped server-side
via the `where` clause.

Idempotent: skips work if data/eer_geoms.json already exists unless
--force. The raw GeoJSON is cached at data/source/eer_dec_2018_uk_bgc.geojson.
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
OUT = DATA / "eer_geoms.json"
RAW_CACHE = SOURCE / "eer_dec_2018_uk_bgc.geojson"

EER_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/'
    'EER_Dec_2018_GCB_UK_2022/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

# Match the EP results pipeline + the `gb` viewBox: keep England + Scotland
# + Wales, drop NI. Strings are full GSS-style EER codes (eer18cd).
GB_EER_PREFIXES = ('E15', 'S15', 'W08')

# EERs are regional-scale polygons (median ~14,000 km²) with detailed
# coastlines and lots of small islands (especially Scotland), so the
# 100 m tolerance used by smaller overlays produces a ~1 MB artifact.
# 500 m simplification stays invisible on a ~700 px GB canvas while
# dropping the artifact to ~150 KB — same trade-off the country-level
# layer would want.
SIMPLIFY_TOLERANCE_M = 500


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_eer_geom() -> dict:
    """Fetch all 12 EER features. The layer only has 12 records so
    pagination isn't needed (default page size 1000); we still ask for
    GeoJSON in EPSG:27700 for the y-flip downstream."""
    params = {
        'where':          "eer18cd LIKE 'E15%' OR eer18cd LIKE 'S15%' "
                          "OR eer18cd LIKE 'W08%'",
        'outFields':      'eer18cd,eer18nm',
        'returnGeometry': 'true',
        'outSR':          27700,
        'f':              'geojson',
        'orderByFields':  'eer18cd',
    }
    d = http_get(EER_GEOM_ENDPOINT, params)
    if isinstance(d, dict) and d.get('error'):
        raise RuntimeError(f'EER geometry query failed: {d["error"]}')
    return d


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """Same y-flip + integer-rounding recipe as scripts/09 / 16 / 21 / 27 / 28."""
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
    in data/ward_geoms.json. Same approach as scripts/16 / 21 / 27 / 28."""
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
        print('1. Fetching EER_Dec_2018_GCB_UK_2022 from ONS BGC FeatureServer...')
        fc = fetch_eer_geom()
        with open(RAW_CACHE, 'w') as f:
            json.dump(fc, f)
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')

    # 11 GB EERs (9 English + Scotland + Wales). NI is dropped server-side
    # via the `where` clause; if anything else comes through, log it.
    n_feat = len(fc['features'])
    if n_feat != 11:
        print(f'  WARN: expected 11 GB EER features, got {n_feat} — '
              f'continuing anyway')

    print('2. Reading GB y bounds from ward_geoms.json so EER paths share '
          'the wards\' SVG coord space...')
    min_y, max_y = read_gb_y_bounds()
    print(f'   gb y-range = [{min_y:.0f}, {max_y:.0f}]')

    print('3. Loading, simplifying, emitting SVG paths...')
    gdf = gpd.GeoDataFrame.from_features(fc['features'], crs='EPSG:27700')

    regions: dict[str, dict] = {}
    for _, row in gdf.iterrows():
        code = row['eer18cd']
        if not code.startswith(GB_EER_PREFIXES):
            continue
        name = row['eer18nm']
        simplified = row.geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
        regions[code] = {
            'path': polygon_to_path(simplified, max_y, min_y),
            'name': name,
        }

    out_data = {'regions': regions}
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    print(
        f'\nDone. wrote {len(regions)} EER polygon(s) · '
        f'{size_kb:.1f} KB → {OUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
