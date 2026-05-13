"""Fetch and pre-process ONS SPC26 (Scottish Parliament constituency) boundaries.

Sibling to scripts/09b_fetch_ced_boundaries.py. Adds an `spcs` dict to
data/ward_geoms.json — one record per Scottish Parliament constituency,
keyed by SPC26CD, with the same SVG-path / name shape the existing
`wards`, `boroughs` and `ceds` dicts use.

Used by scripts/07d_build_current_map_artifact.py to render the 73
Holyrood constituency polygons on top of the 2022 STV Scottish council
wards on the Current map (issue #21). Since the 7 May 2026 Scottish
Parliament election is newer than every Scottish council contest the
page currently colours, the SPC layer paints Scotland wall-to-wall under
the "most recent vote" default view.

Boundaries: the 7 May 2026 election was the first contested on the
post-2024-review Holyrood map (Boundaries Commission for Scotland's
"First Review of Scottish Parliament Boundaries"). ONS publishes the new
geometry as SPC_MAY_2026_SC_BGC; the SPC_DEC_2022 layer reflects the
pre-review 2017 boundaries used by the Sixth Parliament 2021-2026 and is
NOT a fit for the 2026 results (~20 constituencies renamed/redrawn).

Pipeline:
  1. Fetch SPC_MAY_2026_SC_BGC (BGC = Generalised Clipped, already in
     EPSG:27700). One feature per constituency (73 features) with
     SPC26CD + SPC26NM attributes.
  2. Simplify at 50 m tolerance (same as wards / CEDs).
  3. Y-flip and emit SVG path strings in the same global coordinate
     system used by the existing ward + borough + CED paths in
     data/ward_geoms.json, so viewBoxes don't need re-computing.
  4. Merge into the existing ward_geoms.json under a new `spcs` key;
     bail if the file doesn't exist (run 09 first).

Build-only; same geopandas / shapely deps as 09 / 09b. Idempotent —
skips work if the output already has an `spcs` key unless --force.
"""
import argparse
import gzip
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "ward_geoms.json"
RAW_CACHE = SOURCE / "spc_may_2026_sc_bgc.geojson"

SPC_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'SPC_MAY_2026_SC_BGC/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

SPC_SIMPLIFY_TOLERANCE_M = 50


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_spc_geom() -> dict:
    """Page through the SPC26 BGC FeatureServer. Returns a GeoJSON
    FeatureCollection in EPSG:27700 (BNG), the layer's native CRS — no
    reprojection needed downstream."""
    page_size = 1000
    offset = 0
    all_features = []
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'SPC26CD,SPC26NM',
            'returnGeometry':    'true',
            'outSR':             27700,
            'f':                 'geojson',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     'SPC26CD',
        }
        d = http_get(SPC_GEOM_ENDPOINT, params)
        if isinstance(d, dict) and d.get('error'):
            raise RuntimeError(f'SPC geometry query failed: {d["error"]}')
        feats = d.get('features', [])
        all_features.extend(feats)
        print(f'  geometry page offset={offset} → {len(feats)} SPCs '
              f'(running total {len(all_features)})')
        if not d.get('exceededTransferLimit') and len(feats) < page_size:
            break
        offset += len(feats)
        time.sleep(0.3)
    return {'type': 'FeatureCollection', 'features': all_features}


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """SVG path with y-flip applied; same convention as scripts/09 + 09b."""
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true', help='Re-run even if `spcs` already in ward_geoms.json')
    args = ap.parse_args()

    if not OUT.exists():
        raise SystemExit(
            f'{OUT.relative_to(ROOT)} not found — run scripts/09_fetch_ward_boundaries.py first.'
        )
    geoms = json.loads(OUT.read_text())
    if geoms.get('spcs') and not args.force:
        print(f'{OUT.relative_to(ROOT)} already has `spcs` ({len(geoms["spcs"])} '
              f'polygons) — skipping. Use --force to rebuild.')
        return

    SOURCE.mkdir(parents=True, exist_ok=True)

    if RAW_CACHE.exists():
        print(f'1. {RAW_CACHE.relative_to(ROOT)} cached — reusing')
        geom = json.loads(RAW_CACHE.read_text())
    else:
        print('1. Fetching SPC26 geometry from ONS BGC FeatureServer...')
        geom = fetch_spc_geom()
        RAW_CACHE.write_text(json.dumps(geom))
        print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')
    print(f'   got {len(geom["features"])} SPC polygons')

    import geopandas as gpd  # lazy: only needed on rebuilds
    print('2. Loading + simplifying SPC geometry (already in EPSG:27700)...')
    gdf = gpd.GeoDataFrame.from_features(geom['features'], crs='EPSG:27700')
    gdf['geom_s'] = gdf.geometry.simplify(SPC_SIMPLIFY_TOLERANCE_M, preserve_topology=True)

    # Re-use the global y-flip basis 09 used to emit the ward paths.
    # `simplify(preserve_topology=True)` preserves total_bounds (vertex removal
    # doesn't move extrema), so the basis is also the BNG y-range that the SVG
    # ends up in — and that range is recoverable straight from viewBoxes['gb']
    # (= [minx, miny, w, h] in the shared SVG/BNG coordinate space).
    #
    # That fallback path matters for fresh checkouts: the raw ward cache is
    # ~50 MB and gitignored, so requiring it to compute SPC paths would force
    # a full re-fetch of 09 just to add 73 polygons. The viewBox approach
    # gives a byte-identical basis and keeps 09d standalone.
    raw_ward_cache = SOURCE / 'wd_may_2024_uk_bgc_gb.geojson'
    if raw_ward_cache.exists():
        print('   reloading ward bounds for y-flip basis alignment...')
        ward_gdf = gpd.GeoDataFrame.from_features(
            json.loads(raw_ward_cache.read_text())['features'], crs='EPSG:4326'
        ).to_crs(27700)
        w_minx, w_miny, w_maxx, w_maxy = ward_gdf.geometry.total_bounds
    else:
        gb_vb = geoms.get('viewBoxes', {}).get('gb')
        if not gb_vb:
            raise SystemExit(
                'data/ward_geoms.json has no viewBoxes["gb"] — re-run '
                'scripts/09_fetch_ward_boundaries.py to populate it.'
            )
        # viewBox is [minx, miny, w, h] in the y-flipped SVG space, which equals
        # the BNG y-range (the flip just inverts within that range).
        w_minx, w_miny = gb_vb[0], gb_vb[1]
        w_maxx, w_maxy = gb_vb[0] + gb_vb[2], gb_vb[1] + gb_vb[3]
        print('   raw ward cache missing — recovering y-flip basis from viewBoxes["gb"]')
    print(f'   ward bounds (BNG): x[{w_minx:.0f}..{w_maxx:.0f}], y[{w_miny:.0f}..{w_maxy:.0f}]')

    print('3. Emitting per-SPC SVG paths (y-flipped to match ward paths)...')
    spcs_out = {}
    for _, row in gdf.iterrows():
        code = row['SPC26CD']
        spcs_out[code] = {
            'path': polygon_to_path(row['geom_s'], w_maxy, w_miny),
            'name': row['SPC26NM'],
        }
    geoms['spcs'] = spcs_out
    OUT.write_text(json.dumps(geoms, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    gz_kb = len(gzip.compress(OUT.read_bytes())) / 1024
    print(f'\nDone. {OUT.relative_to(ROOT)} now carries '
          f'{len(geoms["spcs"])} SPC polygons · total file '
          f'{size_kb:.1f} KB (gzip {gz_kb:.1f} KB)')


if __name__ == '__main__':
    main()
