"""Fetch and pre-process ONS CED25 (County Electoral Division) boundaries.

Sibling to scripts/09_fetch_ward_boundaries.py. Adds a `ceds` dict to
data/ward_geoms.json — one record per English county-electoral division,
keyed by CED25CD, with the same SVG-path / name / parent-LAD shape the
existing `wards` and `boroughs` dicts use.

Used by scripts/07d_build_current_map_artifact.py to render an optional
CED polygon layer over the ward fills, so 2-tier areas can be coloured
by their county-council CED winner alongside (or instead of) the
district-council ward winner.

Pipeline:
  1. Fetch CED_MAY_2025_EN_BGC (BGC = Generalised Clipped, already in
     EPSG:27700). One feature per CED in England (~1,800 features), with
     CED25CD + CED25NM attributes.
  2. Fetch WD25_LAD25_CTY25_CED25_EN_LU to get the CED25 → CTY25CD
     parent-county lookup so the renderer can show context in tooltips.
     The WD25 column is incidentally also a ward→CED lookup the
     renderer can use for tooltip enrichment on individual wards.
  3. Simplify at 50 m tolerance (same as wards — CEDs are similar size).
  4. Y-flip and emit SVG path strings in the same global coordinate
     system used by the existing ward + borough paths in
     data/ward_geoms.json, so viewBoxes don't need re-computing.
  5. Merge into the existing ward_geoms.json under a new `ceds` key;
     bail if the file doesn't exist (run 09 first).

Build-only; same geopandas / shapely deps as 09. Idempotent — skips
work if the output already has a `ceds` key unless --force is passed.
"""
import argparse
import gzip
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

# geopandas + shapely are only needed when re-fetching CED geometry. The
# fast path (ward_to_ced refresh on an existing ward_geoms.json) avoids the
# heavy geo deps; we import them lazily inside main() when `need_geometry`
# is True.

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "ward_geoms.json"
RAW_CACHE = SOURCE / "ced_may_2025_en_bgc.geojson"

CED_GEOM_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'CED_MAY_2025_EN_BGC/FeatureServer/0/query'
)
CED_LU_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'WD25_LAD25_CTY25_CED25_EN_LU/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

CED_SIMPLIFY_TOLERANCE_M = 50


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_ced_geom() -> dict:
    """Page through the CED25 BGC FeatureServer (server caps each request).
    Returns a GeoJSON FeatureCollection in EPSG:27700 (BNG), the layer's
    native CRS — no reprojection needed downstream."""
    page_size = 1000
    offset = 0
    all_features = []
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'CED25CD,CED25NM',
            'returnGeometry':    'true',
            'outSR':             27700,
            'f':                 'geojson',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     'CED25CD',
        }
        d = http_get(CED_GEOM_ENDPOINT, params)
        # ArcGIS REST GeoJSON output puts errors in the top-level dict;
        # mirror the 09-side error path.
        if isinstance(d, dict) and d.get('error'):
            raise RuntimeError(f'CED geometry query failed: {d["error"]}')
        feats = d.get('features', [])
        all_features.extend(feats)
        print(f'  geometry page offset={offset} → {len(feats)} CEDs '
              f'(running total {len(all_features)})')
        if not d.get('exceededTransferLimit') and len(feats) < page_size:
            break
        offset += len(feats)
        time.sleep(0.3)
    return {'type': 'FeatureCollection', 'features': all_features}


def fetch_ced_county_lookup() -> tuple[dict, dict]:
    """Fetch the WD25_LAD25_CTY25_CED25 lookup and split it two ways.

    Returns (ced_meta, ward_to_ced):
      ced_meta:     {CED25CD: {'name', 'cty', 'cty_name', 'lad'}} — keyed by CED.
      ward_to_ced:  {WD25CD: CED25CD} — every WD25 ward in a 2-tier English
                    district. Used downstream (04c) to enrich the per-ward
                    Current-page tooltip with its parent CED winner.

    The lookup has one row per (ward, CED) pair, so we de-dup on each side."""
    page_size = 2000
    offset = 0
    ced_meta: dict[str, dict] = {}
    ward_to_ced: dict[str, str] = {}
    while True:
        params = {
            'where':             '1=1',
            'outFields':         'WD25CD,CED25CD,CED25NM,CTY25CD,CTY25NM,LAD25CD',
            'returnGeometry':    'false',
            'f':                 'json',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
        }
        d = http_get(CED_LU_ENDPOINT, params)
        if d.get('error'):
            raise RuntimeError(f'CED lookup query failed: {d["error"]}')
        feats = d.get('features', [])
        for f in feats:
            a = f['attributes']
            ced = a.get('CED25CD')
            if ced and ced not in ced_meta:
                ced_meta[ced] = {
                    'name':     a.get('CED25NM'),
                    'cty':      a.get('CTY25CD'),
                    'cty_name': a.get('CTY25NM'),
                    'lad':      a.get('LAD25CD'),
                }
            wd = a.get('WD25CD')
            if wd and ced and wd not in ward_to_ced:
                ward_to_ced[wd] = ced
        if not d.get('exceededTransferLimit'):
            break
        offset += len(feats)
        time.sleep(0.3)
    return ced_meta, ward_to_ced


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """SVG path with y-flip applied; same convention as scripts/09."""
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
    ap.add_argument('--force', action='store_true', help='Re-run even if `ceds` already in ward_geoms.json')
    args = ap.parse_args()

    if not OUT.exists():
        raise SystemExit(
            f'{OUT.relative_to(ROOT)} not found — run scripts/09_fetch_ward_boundaries.py first.'
        )
    geoms = json.loads(OUT.read_text())
    if geoms.get('ceds') and geoms.get('ward_to_ced') and not args.force:
        print(f'{OUT.relative_to(ROOT)} already has `ceds` + `ward_to_ced` — '
              f'skipping. Use --force to rebuild.')
        return

    SOURCE.mkdir(parents=True, exist_ok=True)

    # Geometry pass: skip when the file already has `ceds` and the caller
    # isn't forcing a rebuild. CED polygons are an append-only y-flipped
    # render of the ONS BGC dataset — re-computing them costs ~50 MB of
    # ONS fetches, geopandas/shapely processing, and the wd raw-cache
    # dependency on scripts/09. When all we need is the new `ward_to_ced`
    # key (issue #8 quick-win), skipping the geometry pass keeps the
    # script runnable on a checkout that hasn't fetched the ward
    # raw-cache yet.
    need_geometry = args.force or not geoms.get('ceds')
    if need_geometry:
        if RAW_CACHE.exists():
            print(f'1. {RAW_CACHE.relative_to(ROOT)} cached — reusing')
            geom = json.loads(RAW_CACHE.read_text())
        else:
            print('1. Fetching CED25 geometry from ONS BGC FeatureServer...')
            geom = fetch_ced_geom()
            RAW_CACHE.write_text(json.dumps(geom))
            print(f'   cached → {RAW_CACHE.relative_to(ROOT)}')
        print(f'   got {len(geom["features"])} CED polygons')
    else:
        print(f'1. {OUT.relative_to(ROOT)} already has {len(geoms["ceds"])} '
              f'`ceds` polygons — skipping geometry pass. '
              f'Pass --force to rebuild them too.')

    print('2. Fetching CED → CTY (parent county) lookup...')
    ced_meta, ward_to_ced = fetch_ced_county_lookup()
    print(f'   got {len(ced_meta)} CED → county mappings, '
          f'{len(ward_to_ced)} ward → CED entries')

    if need_geometry:
        import geopandas as gpd  # lazy: only needed on full rebuilds
        print('3. Loading + simplifying CED geometry (already in EPSG:27700)...')
        gdf = gpd.GeoDataFrame.from_features(geom['features'], crs='EPSG:27700')
        gdf['geom_s'] = gdf.geometry.simplify(CED_SIMPLIFY_TOLERANCE_M, preserve_topology=True)

        # Use the SAME global y-flip basis as ward_geoms uses: the GB total bounds
        # of the ward set. We don't have them on hand here, but ward `path` strings
        # were written with that basis. Reload the raw ward geom cache and union
        # its bounds to recover that basis.
        raw_ward_cache = SOURCE / 'wd_may_2024_uk_bgc_gb.geojson'
        if not raw_ward_cache.exists():
            raise SystemExit(
                f'{raw_ward_cache.relative_to(ROOT)} missing — needed to recover the '
                'global y-flip basis. Re-run scripts/09_fetch_ward_boundaries.py.'
            )
        print('   reloading ward bounds for y-flip basis alignment...')
        ward_gdf = gpd.GeoDataFrame.from_features(
            json.loads(raw_ward_cache.read_text())['features'], crs='EPSG:4326'
        ).to_crs(27700)
        w_minx, w_miny, w_maxx, w_maxy = ward_gdf.geometry.total_bounds
        print(f'   ward bounds (BNG): x[{w_minx:.0f}..{w_maxx:.0f}], y[{w_miny:.0f}..{w_maxy:.0f}]')

        print('4. Emitting per-CED SVG paths (y-flipped to match ward paths)...')
        ceds_out = {}
        for _, row in gdf.iterrows():
            ced_code = row['CED25CD']
            meta = ced_meta.get(ced_code, {})
            ceds_out[ced_code] = {
                'path':     polygon_to_path(row['geom_s'], w_maxy, w_miny),
                'name':     row['CED25NM'],
                'cty':      meta.get('cty'),
                'cty_name': meta.get('cty_name'),
                'lad':      meta.get('lad'),
            }
        geoms['ceds'] = ceds_out
    geoms['ward_to_ced'] = ward_to_ced
    OUT.write_text(json.dumps(geoms, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    gz_kb = len(gzip.compress(OUT.read_bytes())) / 1024
    print(f'\nDone. {OUT.relative_to(ROOT)} now carries '
          f'{len(geoms["ceds"])} CED polygons and '
          f'{len(ward_to_ced)} ward→CED entries · total file '
          f'{size_kb:.1f} KB (gzip {gz_kb:.1f} KB)')


if __name__ == '__main__':
    main()
