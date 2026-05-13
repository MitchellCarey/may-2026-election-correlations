"""Overlay LGBCE post-review CED polygons onto the CED25 set in ward_geoms.json.

Norfolk, Essex, and Suffolk all had an LGBCE boundary review for the May 2026
election that renamed / split / merged divisions. The ONS CED25 dataset is
pre-review and won't catch up until ONS publishes CED26. Until then, the
LGBCE final-recommendation shapefiles are the authoritative source for the
post-review boundaries.

For each registered county, this script fetches the LGBCE zip (cached
under data/source/lgbce/), reads the shapefile, simplifies at the same
50 m tolerance used by scripts/09 and 09b, and *replaces* the CED25 entries
for that county in data/ward_geoms.json's `ceds` map.

Synthetic keys (cty_code + slugified division name) stand in for the missing
official CED25CDs. They're stable per (county, name) pair, so editing the
ced_winners join keeps working.

Pipeline:
  1. Recover the global y-flip basis from existing ward path coords in
     data/ward_geoms.json — no raw GeoJSON cache needed. The basis is GB-wide,
     so this works as long as scripts/09 has produced a complete ward set.
  2. For each county in REVIEWS:
       a. Fetch the LGBCE zip from lgbce.org.uk if not already cached
       b. Extract, read the shapefile via geopandas (already in EPSG:27700)
       c. Simplify, build SVG paths
       d. Strip ' ED' suffix from the LGBCE name field (Norfolk uses bare
          names, Essex/Suffolk use 'X ED' — normalise here so the
          name in ward_geoms.json matches the council's published 2026
          division name as it appears in county_official_2026.csv)
  3. Delete every existing ceds[*] entry whose `cty` matches a reviewed
     county; insert the new entries under synthetic keys.
  4. Write back ward_geoms.json.

Build-only — geopandas/shapely already in requirements.txt. Idempotent; skip
work if every reviewed county already has post-review entries unless --force.
"""
import argparse
import json
import re
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
LGBCE_CACHE = SOURCE / "lgbce"
OUT = DATA / "ward_geoms.json"
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

CED_SIMPLIFY_TOLERANCE_M = 50

# Per-county LGBCE final-recommendation shapefile sources. Each tuple is the
# enacted-order final-recommendation zip; the relative shapefile path inside
# the extracted dir; and the column name carrying the division name. Sourced
# by reading the LGBCE review page for each county and copying the 'Final
# recommendation' shapefile link.
REVIEWS = [
    {
        'cty_code':       'E10000020',
        'cty_name':       'Norfolk',
        'zip_url':        'https://www.lgbce.org.uk/sites/default/files/2025-01/norfolk_final_proposals.zip',
        'zip_name':       'norfolk_final_proposals.zip',
        'shapefile':      'Norfolk_final_proposals.shp',
        'name_column':    'Division_n',
    },
    {
        'cty_code':       'E10000012',
        'cty_name':       'Essex',
        'zip_url':        'https://www.lgbce.org.uk/sites/default/files/2024-07/essex_f_so_zipfiles.zip',
        'zip_name':       'essex_f_so_zipfiles.zip',
        'shapefile':      'Essex_F_SO_zipfiles/Essex_F_Electoral_Division_polygons.shp',
        'name_column':    'Name',
    },
    {
        'cty_code':       'E10000029',
        'cty_name':       'Suffolk',
        'zip_url':        'https://www.lgbce.org.uk/sites/default/files/2024-10/suffolk_f_ed_polys.zip',
        'zip_name':       'suffolk_f_ed_polys.zip',
        'shapefile':      'Suffolk_F_ED_polys.shp',
        'name_column':    'WardName',
    },
]

# Per-county name fixes (left = raw LGBCE shapefile string, right = canonical
# division name as used in council-published 2026 results / county_official_2026.csv).
# The shapefile names are mostly canonical post strip-' ED' but a few carry
# typos or 'with' vs '&' that won't normalise away.
NAME_FIXES = {
    # Suffolk: shapefile has duplicated suffix; strip_ed_suffix removes one,
    # leaving "Newmarket & Red Lodge ED" — strip the second here.
    'Newmarket & Red Lodge ED': 'Newmarket & Red Lodge',
    # Essex: 'Parndon' is the correct historic name; the council's published
    # CSV uses the typo 'Pardon'. Conform to CSV so the name-based join succeeds.
    'Harlow Parndon & Toddbrook': 'Harlow Pardon and Toddbrook',
    # Essex: LGBCE used '&'; the council CSV uses 'with' (verified in
    # county_official_2026.csv). Conform to CSV.
    'Three Fields & Great Notley': 'Three Fields with Great Notley',
    # Norfolk: LGBCE collapses to one word; council CSV keeps two.
    'Yarmouth Nelson & Southtown': 'Yarmouth Nelson and South Town',
}


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
    return s


def strip_ed_suffix(name: str) -> str:
    return re.sub(r'\s+ED\s*$', '', name).strip()


def recover_yflip_basis(geoms: dict) -> tuple[int, int]:
    """Read every existing ward path and recover (min_y_bng, max_y_bng).

    Paths were written by scripts/09 with the formula
        y_svg = max_y_bng - y_bng + min_y_bng
    over the full GB ward set. Inverted: y_bng = max_y_bng - y_svg + min_y_bng.
    The numeric range of y_svg values therefore equals the BNG y range
    (max_y_bng, min_y_bng), so observing min(y_svg) → min_y_bng and
    max(y_svg) → max_y_bng across all paths gives us the basis directly —
    no raw GeoJSON re-fetch required.
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
    """SVG path with the same y-flip convention as scripts/09 and 09b.

    Some LGBCE shapefiles carry POLYGON Z geometry (z=0); ignore the third
    coord by slicing the first two from each tuple.
    """
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


def fetch_zip(url: str, dest: Path) -> None:
    if dest.exists():
        print(f'   cached → {dest.relative_to(ROOT)}')
        return
    print(f'   fetching {url}')
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())


def extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract every file in the zip into dest_dir (preserving sub-paths).

    Some LGBCE zips (e.g. Essex's) use Deflate64 — Python's stdlib zipfile
    doesn't support it, so we fall back to the system `unzip` tool. macOS
    and most Linux distros ship it.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest_dir)
    except NotImplementedError:
        import subprocess
        subprocess.run(
            ['unzip', '-q', '-o', str(zip_path), '-d', str(dest_dir)],
            check=True,
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true',
                    help='Rebuild even if every reviewed county already has post-review entries')
    args = ap.parse_args()

    if not OUT.exists():
        raise SystemExit(
            f'{OUT.relative_to(ROOT)} not found — run scripts/09_fetch_ward_boundaries.py first.'
        )
    geoms = json.loads(OUT.read_text())
    if not geoms.get('ceds'):
        raise SystemExit(
            f'{OUT.relative_to(ROOT)} has no `ceds` key — run scripts/09b_fetch_ced_boundaries.py first.'
        )

    reviewed_codes = {r['cty_code'] for r in REVIEWS}
    have_post_review = {
        meta['cty'] for code, meta in geoms['ceds'].items()
        if code.startswith('LGBCE_') and meta.get('cty') in reviewed_codes
    }
    if reviewed_codes <= have_post_review and not args.force:
        print(f'{OUT.relative_to(ROOT)} already has post-review CEDs for all '
              f'{len(reviewed_codes)} reviewed counties — skipping. Use --force to rebuild.')
        return

    LGBCE_CACHE.mkdir(parents=True, exist_ok=True)

    print(f'1. Recovering y-flip basis from {len(geoms["wards"])} ward paths...')
    min_y, max_y = recover_yflip_basis(geoms)
    print(f'   BNG y range: [{min_y}, {max_y}]')

    print('2. Fetching + reading LGBCE shapefiles for reviewed counties...')
    new_entries: dict[str, dict] = {}
    for review in REVIEWS:
        cty = review['cty_code']
        name = review['cty_name']
        print(f'  - {name} ({cty})')
        zip_path = LGBCE_CACHE / review['zip_name']
        fetch_zip(review['zip_url'], zip_path)
        # Always extract — geopandas can't read directly from inside a zip
        # without GDAL VSI quoting, and extracting is fast.
        extract_zip(zip_path, LGBCE_CACHE)
        shp = LGBCE_CACHE / review['shapefile']
        if not shp.exists():
            raise RuntimeError(f'{shp.relative_to(ROOT)} missing after unzipping {zip_path.name}')

        gdf = gpd.read_file(shp)
        if gdf.crs is None or gdf.crs.to_epsg() != 27700:
            gdf = gdf.to_crs(27700)
        gdf['geom_s'] = gdf.geometry.simplify(CED_SIMPLIFY_TOLERANCE_M, preserve_topology=True)

        # Dissolve duplicate-name rows into one polygon per division (Norfolk's
        # shapefile has one division split across two records).
        col = review['name_column']
        gdf[col] = gdf[col].fillna('')
        dissolved = gdf.dissolve(by=col, aggfunc='first', sort=False)
        dissolved = dissolved.reset_index()
        dissolved['geom_s'] = dissolved.geometry.simplify(CED_SIMPLIFY_TOLERANCE_M, preserve_topology=True)

        n_for_county = 0
        for _, row in dissolved.iterrows():
            raw = row[col].strip()
            stripped = strip_ed_suffix(raw)
            canonical = NAME_FIXES.get(stripped, stripped)
            if not canonical:
                continue
            key = f'LGBCE_{cty}_{slugify(canonical)}'
            new_entries[key] = {
                'path':     polygon_to_path(row['geom_s'], max_y, min_y),
                'name':     canonical,
                'cty':      cty,
                'cty_name': name,
            }
            n_for_county += 1
        print(f'    → {n_for_county} divisions emitted')

    print('3. Replacing CED25 entries for reviewed counties...')
    old_ceds = geoms['ceds']
    kept = {
        code: meta for code, meta in old_ceds.items()
        if meta.get('cty') not in reviewed_codes
    }
    removed = len(old_ceds) - len(kept)
    kept.update(new_entries)
    geoms['ceds'] = kept
    print(f'   removed {removed} CED25 entries; inserted {len(new_entries)} LGBCE entries')
    print(f'   ceds count: {len(old_ceds)} → {len(kept)}')

    OUT.write_text(json.dumps(geoms, separators=(',', ':')))
    print(f'\nDone. {OUT.relative_to(ROOT)} updated.')


if __name__ == '__main__':
    main()
