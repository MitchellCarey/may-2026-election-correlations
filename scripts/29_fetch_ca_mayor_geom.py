"""Fetch Combined-Authority (CA) polygons from the ONS Open Geography
Portal and emit data/ca_mayor_geoms.json.

Sibling to scripts/28_fetch_gla_mayor_geom.py — same y-flip + shared-bounds
recipe so each CA polygon lands in the same SVG coord space as wards,
boroughs, CEDs, Holyrood SPCs, Senedd constituencies, PCONs and the GLA
Mayor outline.

Two ONS snapshots are needed because the North of Tyne CA (E47000011) was
abolished and reformed as the North East CA (E47000014) in May 2024 with
four additional LADs (Durham, Gateshead, South Tyneside, Sunderland):

- Combined_Authorities_December_2025_Boundaries_EN_BGC — 15 features. We
  keep 13 (filtering out E47000015 Devon and Torbay + E47000018 Lancashire,
  which have established CAA/CCAs but no mayor on record yet).
- Combined_Authorities_December_2023_Boundaries_EN_BGC — 10 features. We
  keep 1 (E47000011 North of Tyne) which the December 2025 snapshot no
  longer carries.

Both ONS feeds use BGC (Generalised Clipped — every other ONS fetcher in
this repo uses BGC: 09 / 16 / 16b / 21 / 21b / 27 / 28). Native CRS is
EPSG:27700 (British National Grid) so no reprojection is needed.

Idempotent: skips work if data/ca_mayor_geoms.json already exists unless
--force. Raw GeoJSON snapshots cache at:
  data/source/combined_authorities_dec_2025.geojson  (post-era)
  data/source/combined_authorities_dec_2023.geojson  (pre-era)
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
OUT = DATA / "ca_mayor_geoms.json"
RAW_POST = SOURCE / "combined_authorities_dec_2025.geojson"
RAW_PRE = SOURCE / "combined_authorities_dec_2023.geojson"

CAUTH_2025_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'Combined_Authorities_December_2025_Boundaries_EN_BGC/FeatureServer/0/query'
)
CAUTH_2023_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'Combined_Authorities_December_2023_Boundaries_EN_BGC/FeatureServer/0/query'
)

# Codes the registry actually paints. Devon & Torbay (E47000015) and
# Lancashire (E47000018) are dropped from the Dec 2025 snapshot here —
# they have no mayoral election on record. The registry stays the source
# of truth; this list is a defensive filter so a future probe of the same
# ONS layer doesn't accidentally paint a non-mayoral entity.
POST_KEEP_CODES = {
    'E47000001', 'E47000002', 'E47000003', 'E47000004', 'E47000006',
    'E47000007', 'E47000008', 'E47000009', 'E47000012', 'E47000013',
    'E47000014', 'E47000016', 'E47000017',
}
PRE_KEEP_CODES = {'E47000011'}  # North of Tyne (abolished May 2024)

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

# Same tolerance as Senedd / PCON / GLA — CA outlines are at regional
# scale, 100 m is invisible at the ~700 px GB canvas.
SIMPLIFY_TOLERANCE_M = 100


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_cauth(endpoint: str, code_field: str) -> dict:
    """Fetch every CAUTH feature in the layer as EPSG:27700 GeoJSON."""
    params = {
        'where':          '1=1',
        'outFields':      f'{code_field},{code_field.replace("CD", "NM")}',
        'returnGeometry': 'true',
        'outSR':          27700,
        'f':              'geojson',
    }
    d = http_get(endpoint, params)
    if isinstance(d, dict) and d.get('error'):
        raise RuntimeError(f'CAUTH geometry query failed: {d["error"]}')
    return d


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
    """Same y-flip + integer-rounding recipe as scripts/09 / 16 / 21 / 28."""
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
    data/ward_geoms.json. Same approach as scripts/16 / 21 / 28."""
    with open(DATA / 'ward_geoms.json') as f:
        geoms = json.load(f)
    pattern = re.compile(r'[ML](-?\d+),(-?\d+)')
    ys: list[int] = []
    for w in geoms['wards'].values():
        ys.extend(int(m.group(2)) for m in pattern.finditer(w['path']))
    if not ys:
        raise RuntimeError("could not scan y bounds from ward_geoms.json — empty wards?")
    return float(min(ys)), float(max(ys))


def ensure_raw(path: Path, endpoint: str, code_field: str, label: str) -> dict:
    if path.exists():
        print(f'1. {path.relative_to(ROOT)} cached — reusing ({label})')
        with open(path) as f:
            return json.load(f)
    print(f'1. Fetching {label} CAUTH BGC boundary GeoJSON from ONS...')
    fc = fetch_cauth(endpoint, code_field)
    with open(path, 'w') as f:
        json.dump(fc, f)
    print(f'   cached → {path.relative_to(ROOT)}')
    return fc


def simplify_features(fc: dict, code_field: str, name_field: str,
                      keep_codes: set[str], max_y: float, min_y: float
                      ) -> dict[str, dict]:
    gdf = gpd.GeoDataFrame.from_features(fc['features'], crs='EPSG:27700')
    out: dict[str, dict] = {}
    skipped: list[str] = []
    for _, row in gdf.iterrows():
        code = row[code_field]
        if code not in keep_codes:
            skipped.append(f'{code} ({row[name_field]})')
            continue
        simplified = row.geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
        out[code] = {
            'path': polygon_to_path(simplified, max_y, min_y),
            'name': row[name_field],
        }
    if skipped:
        print(f'   skipped {len(skipped)}: {", ".join(skipped)}')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true', help='Re-run even if outputs exist')
    args = ap.parse_args()

    if OUT.exists() and not args.force:
        print(f'{OUT.relative_to(ROOT)} exists — skipping. Use --force to rebuild.')
        return

    SOURCE.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    fc_post = ensure_raw(RAW_POST, CAUTH_2025_ENDPOINT, 'CAUTH25CD', 'Dec 2025')
    fc_pre = ensure_raw(RAW_PRE, CAUTH_2023_ENDPOINT, 'CAUTH23CD', 'Dec 2023')

    print('2. Reading GB y bounds from ward_geoms.json so CA polygons '
          'share the wards\' SVG coord space...')
    min_y, max_y = read_gb_y_bounds()
    print(f'   gb y-range = [{min_y:.0f}, {max_y:.0f}]')

    print('3. Simplifying + y-flipping post-era polygons (Dec 2025 snapshot)...')
    post_regions = simplify_features(
        fc_post, 'CAUTH25CD', 'CAUTH25NM', POST_KEEP_CODES, max_y, min_y
    )
    missing_post = POST_KEEP_CODES - set(post_regions)
    if missing_post:
        raise RuntimeError(
            f'Dec 2025 snapshot is missing {len(missing_post)} expected CA(s): '
            f'{sorted(missing_post)}'
        )

    print('4. Simplifying + y-flipping pre-era polygons (Dec 2023 snapshot)...')
    pre_regions = simplify_features(
        fc_pre, 'CAUTH23CD', 'CAUTH23NM', PRE_KEEP_CODES, max_y, min_y
    )
    missing_pre = PRE_KEEP_CODES - set(pre_regions)
    if missing_pre:
        raise RuntimeError(
            f'Dec 2023 snapshot is missing {len(missing_pre)} expected pre-era CA(s): '
            f'{sorted(missing_pre)}'
        )

    out_data = {
        'regions': post_regions,
        'regions_pre': pre_regions,
    }
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, separators=(',', ':')))

    size_kb = OUT.stat().st_size / 1024
    print(
        f'\nDone. wrote {len(post_regions)} post-era + {len(pre_regions)} pre-era '
        f'CA polygons · {size_kb:.1f} KB → {OUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
