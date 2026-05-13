"""Fetch the LGBCE Surrey post-review electoral-division polygons,
split them into East / West Surrey unitaries, simplify + y-flip into the
shared GB SVG coord space, and emit data/surrey_geoms.json.

Sibling to scripts/09c_overlay_lgbce_ceds.py — same shapefile flavour,
same y-flip recipe — but instead of replacing CED25 entries in
ward_geoms.json::ceds, this script writes a standalone overlay file
that 07c and 07d consume on `--region=gb`.

Why the LGBCE shapefile is the right source:
- West Surrey explicitly used "the revised Surrey County Council
  boundaries for the cancelled 2025 elections" — the May 2024 LGBCE
  final-recommendation divisions. The shapefile fields drop straight in.
- East Surrey used "a modified set of boundaries derived from the
  Surrey County Council division boundaries… last used in the 2021 SCC
  election". In practice the LGBCE shapefile covers every East Surrey
  predecessor district (Elmbridge, Epsom & Ewell, Mole Valley,
  Reigate & Banstead, Tandridge) with 36 polygons that map 1:1 to the
  36 wiki wards, save one multipart division ("East Molesey & The
  Dittons") that East Surrey split into two named wards. See SPLITS.

Idempotent: skips work if data/surrey_geoms.json already exists unless
--force is passed. The raw zip is cached under data/source/lgbce/.
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
WARD_GEOMS = DATA / "ward_geoms.json"
OUT = DATA / "surrey_geoms.json"

ZIP_URL = 'https://www.lgbce.org.uk/sites/default/files/2024-05/surrey_mapping_files.zip'
ZIP_NAME = 'surrey_mapping_files.zip'
SHAPEFILE = 'Surrey_F_EDs_polygons.shp'
NAME_COL = 'Division_n'
DISTRICT_COL = 'District'

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'

SIMPLIFY_TOLERANCE_M = 50

# East Surrey predecessor districts (matched against the LGBCE District
# column). Hardcoded as names because the shapefile uses district names
# rather than ONS codes; see _surrey_unitaries.py for the GSS-code
# provenance.
EAST_DISTRICTS = {
    'Elmbridge', 'Epsom & Ewell', 'Mole Valley', 'Reigate & Banstead', 'Tandridge',
}
WEST_DISTRICTS = {
    'Guildford', 'Runnymede', 'Spelthorne', 'Surrey Heath', 'Waverley', 'Woking',
}

# Manual fixes for the one NaN row in the LGBCE shapefile. Shalford ED has
# no Ward_name / Division_n / District filled in; from the Name field and
# its geographic position it's clearly in Guildford (West Surrey).
NAN_FIXES = {
    'Shalford ED': {'Division_n': 'Shalford', 'District': 'Guildford'},
}

# Names where the LGBCE shapefile and the Wikipedia article disagree on
# spelling / punctuation. LGBCE → Wikipedia (canonical for tooltip + match).
NAME_NORMALIZATIONS = {
    'Camberley West & Frimley':         'Camberley West and Frimley',
    'Ewell Court, Auriol and Cuddington': 'Ewell Court, Auriol & Cuddington',
    'Nork & Tattenhams':                'Nork & Tattenham',
}

# East Surrey "modified" the LGBCE division "East Molesey & The Dittons"
# (one logical name, two non-contiguous polygons in the shapefile) by
# splitting it into two wards. Sort the two polygons by centroid y and
# assign the northern (Thames-side) polygon to "Thames Ditton & East
# Molesey", the southern to "Long Ditton, Hinchley Wood & Weston Green".
SPLITS = {
    'East Molesey & The Dittons': [
        # (centroid_y_threshold, replacement_division_name)
        # northern polygon
        ('north', 'Thames Ditton & East Molesey'),
        # southern polygon
        ('south', 'Long Ditton, Hinchley Wood & Weston Green'),
    ],
}


def _slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def fetch_zip(dest: Path) -> None:
    if dest.exists():
        print(f'   cached → {dest.relative_to(ROOT)}')
        return
    print(f'   fetching {ZIP_URL}')
    req = urllib.request.Request(ZIP_URL, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())


def extract_zip(zip_path: Path, dest_dir: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest_dir)
    except NotImplementedError:
        import subprocess
        subprocess.run(
            ['unzip', '-q', '-o', str(zip_path), '-d', str(dest_dir)],
            check=True,
        )


def recover_yflip_basis() -> tuple[int, int]:
    """Read every existing ward path in ward_geoms.json and recover
    (min_y, max_y) in BNG — same approach as scripts/09c. Paths were
    written by scripts/09 with y_svg = max_y - y_bng + min_y, so the
    numeric range of y_svg values equals the BNG y range."""
    geoms = json.loads(WARD_GEOMS.read_text())
    coord_re = re.compile(r'[ML](-?\d+),(-?\d+)')
    min_y = max_y = None
    for w in geoms.get('wards', {}).values():
        for m in coord_re.finditer(w['path']):
            y = int(m.group(2))
            min_y = y if min_y is None or y < min_y else min_y
            max_y = y if max_y is None or y > max_y else max_y
    if min_y is None or max_y is None:
        raise RuntimeError('no ward paths in ward_geoms.json to recover y-flip basis')
    return min_y, max_y


def polygon_to_path(poly, max_y: float, min_y: float) -> str:
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


def apply_splits(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rename multipart polygons that should be treated as separate wards.

    The LGBCE shapefile encodes East Molesey & The Dittons as two
    geographically-separate polygons (north + south) sharing one
    Division_n. East Surrey turned this single LGBCE division into two
    wards; rename each polygon to the appropriate ward by centroid y.
    """
    df = gdf.copy()
    for div_name, mapping in SPLITS.items():
        mask = df[NAME_COL] == div_name
        rows = df[mask]
        if len(rows) != len(mapping):
            print(f'  WARN split {div_name!r}: expected {len(mapping)} polygons, '
                  f'found {len(rows)}; skipping split')
            continue
        ys = [(idx, row.geometry.centroid.y) for idx, row in rows.iterrows()]
        # Sort south → north so we can assign by position
        ys.sort(key=lambda iy: iy[1])
        # mapping[0] is "north" or "south"; build position → new_name from it
        by_pos = {direction: new_name for direction, new_name in mapping}
        south_idx, _ = ys[0]
        north_idx, _ = ys[-1]
        df.loc[south_idx, NAME_COL] = by_pos['south']
        df.loc[north_idx, NAME_COL] = by_pos['north']
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true', help='Re-run even if output exists')
    args = ap.parse_args()

    if OUT.exists() and not args.force:
        print(f'{OUT.relative_to(ROOT)} exists — skipping. Use --force to rebuild.')
        return

    LGBCE_CACHE.mkdir(parents=True, exist_ok=True)

    print('1. Fetching LGBCE Surrey post-review shapefile zip...')
    zip_path = LGBCE_CACHE / ZIP_NAME
    fetch_zip(zip_path)
    extract_zip(zip_path, LGBCE_CACHE)
    shp = LGBCE_CACHE / SHAPEFILE
    if not shp.exists():
        raise RuntimeError(f'{shp.relative_to(ROOT)} missing after unzip')

    print('2. Reading shapefile + repairing the NaN row...')
    gdf = gpd.read_file(shp)
    if gdf.crs is None or gdf.crs.to_epsg() != 27700:
        gdf = gdf.to_crs(27700)
    for name_key, fixes in NAN_FIXES.items():
        mask = gdf['Name'] == name_key
        if mask.sum() == 0:
            print(f'  WARN NAN_FIX target {name_key!r} not found in shapefile')
            continue
        for col, val in fixes.items():
            gdf.loc[mask, col] = val
        print(f'   - filled {mask.sum()} row(s) for {name_key!r} '
              f'({", ".join(f"{k}={v!r}" for k, v in fixes.items())})')

    print('3. Splitting multipart divisions that East Surrey treats as separate wards...')
    gdf = apply_splits(gdf)

    print('4. Normalising shapefile names to match the Wikipedia ward titles...')
    n_renamed = 0
    for old, new in NAME_NORMALIZATIONS.items():
        mask = gdf[NAME_COL] == old
        if mask.sum():
            gdf.loc[mask, NAME_COL] = new
            n_renamed += int(mask.sum())
    print(f'   - {n_renamed} polygon(s) renamed')

    print('5. Dissolving remaining multipart polygons by ward name...')
    gdf[NAME_COL] = gdf[NAME_COL].fillna('')
    gdf[DISTRICT_COL] = gdf[DISTRICT_COL].fillna('')
    dissolved = gdf.dissolve(by=NAME_COL, aggfunc='first', sort=False).reset_index()
    print(f'   - {len(gdf)} feature(s) → {len(dissolved)} ward(s)')

    print('6. Assigning wards to East / West Surrey by predecessor district...')
    east_wards: list[tuple[str, object]] = []
    west_wards: list[tuple[str, object]] = []
    outside: list[str] = []
    for _, row in dissolved.iterrows():
        ward_name = row[NAME_COL]
        district = row[DISTRICT_COL]
        if district in EAST_DISTRICTS:
            east_wards.append((ward_name, row.geometry))
        elif district in WEST_DISTRICTS:
            west_wards.append((ward_name, row.geometry))
        else:
            outside.append(f'{ward_name!r} (District={district!r})')
    print(f'   - East Surrey (XSE): {len(east_wards)} ward(s)')
    print(f'   - West Surrey (XSW): {len(west_wards)} ward(s)')
    if outside:
        print(f'   WARN {len(outside)} polygon(s) assigned to neither unitary:')
        for o in outside:
            print(f'     - {o}')

    print('7. Recovering GB y-flip basis from ward_geoms.json...')
    min_y, max_y = recover_yflip_basis()
    print(f'   BNG y range: [{min_y}, {max_y}]')

    print('8. Simplifying + emitting SVG paths...')
    unitaries: dict[str, dict] = {}
    for lad_code, ward_list in (('XSE', east_wards), ('XSW', west_wards)):
        for ward_name, geom in ward_list:
            simp = geom.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
            code = f'{lad_code}::{_slug(ward_name)}'
            unitaries[code] = {
                'lad':  lad_code,
                'name': ward_name,
                'path': polygon_to_path(simp, max_y, min_y),
            }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({'unitaries': unitaries},
                              ensure_ascii=False, separators=(',', ':')))
    size_kb = OUT.stat().st_size / 1024
    n_xse = sum(1 for c in unitaries if c.startswith('XSE::'))
    n_xsw = sum(1 for c in unitaries if c.startswith('XSW::'))
    print(
        f'\nDone. wrote {len(unitaries)} Surrey unitary wards '
        f'(XSE: {n_xse}, XSW: {n_xsw}, outside: {len(outside)}) · '
        f'{size_kb:.1f} KB → {OUT.relative_to(ROOT)}'
    )


if __name__ == '__main__':
    main()
