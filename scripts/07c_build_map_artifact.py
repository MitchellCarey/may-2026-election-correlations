"""Splice the generated data + map renderer JS into docs/map.html (or
docs/uk/map.html when --region=gb).

Mirror of scripts/07b_build_changes_artifact.py for the Map page. Reads:

  - data/all_wards_with_prior.json (ward records: borough, ward, winner,
    prior_party, flipped, match_type_prior, ...) — filtered to --region.
  - data/ward_geoms.json           (GB-wide ward + council polygons, pre-
    projected to BNG and emitted as SVG path strings, plus a per-region
    viewBox map — see scripts/09)

…joins them via normalised borough+ward name (the geom file is the source of
truth for the WD24 names), and rewrites the block between the BEGIN/END
markers in the target page in place.

Wards present in the geom set but missing from results data (Bury::Moorside,
whose election was cancelled) are still rendered, in neutral grey on every
view. Aborts if any results-side ward fails to join — drift in either
dataset must be investigated, not silently dropped.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import csv

from _artifact_lib import (
    PARTY_COLOURS_MAP as PARTY_COLOURS,
    PARTY_DISPLAY_MAP as PARTY_DISPLAY,
    LEGEND_ORDER_MAP as LEGEND_ORDER,
)
from _councils import lad_codes_for

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

BEGIN = "// ===== BEGIN GENERATED — see scripts/07c_build_map_artifact.py ====="
END = "// ===== END GENERATED ====="


def load_overrides() -> dict:
    """Return {(lad_code, scraped_name): gss_name} — same file 02 uses.
    The 'gss_name' in the CSV is the pre-2024-review Census/ONS ward name,
    which is what the WD24 geom file also carries (the May 2024 ONS
    snapshot pre-dates the August 2024 boundary reviews for the affected
    councils). Wikipedia 2026 headings use the NEW (post-review) names."""
    overrides: dict[tuple[str, str], str] = {}
    with open(ROOT / 'data' / 'source' / 'ward_name_overrides.csv', newline='') as f:
        for row in csv.DictReader(f):
            overrides[(row['lad_code'], row['scraped_name'])] = row['gss_name']
    return overrides


def normalise(s: str) -> str:
    """Loose name match: lowercase, strip dots, slash → space, both apostrophe
    variants → nothing, ' and ' → ' & ', drop a trailing '(...)' disambiguator,
    collapse whitespace. Bridges the punctuation drift between the WD24 names
    in the ONS geom file and the Wikipedia-scraped names in results-side data
    (e.g. 'Dukinfield/Stalybridge' vs 'Dukinfield Stalybridge', 'Kings Heath'
    vs "King's Heath", 'St Mary's' with curly vs straight apostrophe). The
    parenthetical suffix is the Census disambiguator carried in override
    targets (e.g. 'Barnes (Sunderland)') — WD24 itself uses no parens."""
    s = s.lower().replace('/', ' ').replace('.', '')
    s = s.replace("’", "").replace("'", "")
    s = s.replace(' and ', ' & ')
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s)
    return ' '.join(s.split())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--region', default='gm', choices=['gm', 'gb'])
    args = ap.parse_args()
    region = args.region
    region_lad_codes = lad_codes_for(region)
    html_path = DOCS / 'map.html' if region == 'gm' else DOCS / 'uk' / 'map.html'

    with open(DATA / 'all_wards_with_prior.json') as f:
        results = json.load(f)
    with open(DATA / 'ward_geoms.json') as f:
        geoms = json.load(f)

    results = [r for r in results if r.get('lad_code') in region_lad_codes]

    # If the geom file doesn't cover the full region, refuse to splice — a
    # page with only partial shapes is misleading. 09 emits per-region
    # viewBoxes; if `region` isn't one of them, the geom file is stale.
    if region not in geoms.get('viewBoxes', {}):
        print(f'  ! ward_geoms.json has no viewBox for region={region!r} '
              f'(found: {sorted(geoms.get("viewBoxes", {}))}). '
              f'Re-run scripts/09_fetch_ward_boundaries.py --force.',
              file=sys.stderr)
        return
    geom_lads = {w['lad'] for w in geoms['wards'].values()}
    missing = region_lad_codes - geom_lads
    if missing:
        covered = len(region_lad_codes & geom_lads)
        print(f'  ! ward_geoms.json covers {covered}/{len(region_lad_codes)} '
              f'{region} councils; {len(missing)} councils have no geometry. '
              f'Re-run scripts/09_fetch_ward_boundaries.py --force.',
              file=sys.stderr)
        return

    # Restrict geometry to the region's councils so a GB-wide geom file
    # doesn't drag the whole UK into a GM-only page.
    region_wards = {
        code: w for code, w in geoms['wards'].items()
        if w['lad'] in region_lad_codes
    }
    region_boroughs = {
        code: b for code, b in geoms['boroughs'].items()
        if code in region_lad_codes
    }

    # Normalised name → WD24CD lookup; geom file is the source of truth.
    geom_by_norm = {}
    for code, w in region_wards.items():
        borough_name = region_boroughs[w['lad']]['name']
        geom_by_norm[f'{normalise(borough_name)}::{normalise(w["name"])}'] = code

    overrides = load_overrides()

    matched = []
    unmatched = []
    polygon_collisions = []  # 2026 wards whose override target is already claimed
    used_codes = set()
    for r in results:
        key = f'{normalise(r["borough"])}::{normalise(r["ward"])}'
        code = geom_by_norm.get(key)
        via_override = False
        if code is None:
            # Fall back to the override CSV (same one 02 uses for GSS
            # matching). For 2024-boundary-review wards, Wikipedia carries
            # the NEW name while WD24 geom still carries the OLD one — the
            # override maps NEW → OLD so the geom join can finish.
            override = overrides.get((r['lad_code'], r['ward']))
            if override is not None:
                key2 = f'{normalise(r["borough"])}::{normalise(override)}'
                code = geom_by_norm.get(key2)
                via_override = code is not None
        # If an override-resolved polygon is already taken by an earlier
        # ward, don't overwrite — Calderdale gained one ward in the 2024
        # review without a free old-ward proxy, so e.g. Wainhouse and Park
        # both want the same old Park polygon. The direct-match ward
        # (processed first by natural iteration) keeps it; the
        # override-match ward gets dropped from the map.
        if code is not None and via_override and code in used_codes:
            polygon_collisions.append((r['borough'], r['ward']))
            continue
        if code is None:
            unmatched.append((r['borough'], r['ward']))
            continue
        used_codes.add(code)
        matched.append({
            'gss': code,
            'b':   r['borough'],
            'wn':  r['ward'],
            'w':   r.get('winner'),
            'pp':  r.get('prior_party'),
            'py':  r.get('prior_year'),
            'fl':  r.get('flipped'),
            'mp':  r.get('match_type_prior'),
        })

    # Polygons present in the geom set but missing from results (e.g. cancelled
    # Bury::Moorside). Render them in neutral grey on every view.
    no_result = []
    for code, w in region_wards.items():
        if code in used_codes:
            continue
        borough_name = region_boroughs[w['lad']]['name']
        no_result.append({
            'gss': code, 'b': borough_name, 'wn': w['name'],
            'w': None, 'pp': None, 'py': None, 'fl': None, 'mp': None,
        })

    print(f'matched: {len(matched)}/{len(results)} results-side wards joined to a polygon')
    if unmatched:
        for b, w in unmatched:
            print(f'  [UNMATCHED] {b} :: {w}', file=sys.stderr)
        sys.exit(1)
    if polygon_collisions:
        # Not a hard error — these wards are still in the analysis tables;
        # only their polygon overlapped with another ward via the override
        # proxy. Log so it doesn't go silent.
        print(f'  ! {len(polygon_collisions)} ward(s) dropped from the map: '
              f'override polygon already claimed by a direct-match ward:',
              file=sys.stderr)
        for b, w in polygon_collisions:
            print(f'    - {b} :: {w}', file=sys.stderr)
    no_result_names = ', '.join(f'{w["b"]}::{w["wn"]}' for w in no_result)
    print(f'no-result polygons (rendered grey): {len(no_result)}'
          + (f' — {no_result_names}' if no_result else ''))
    print(f'total polygons in WARDS: {len(matched) + len(no_result)}/{len(region_wards)}')

    # Surface any party in the data that we don't have a colour for — the
    # renderer would silently fall back to NEUTRAL_FILL otherwise.
    parties_in_data = {w['w'] for w in matched if w['w']} | {w['pp'] for w in matched if w['pp']}
    unknown = parties_in_data - set(PARTY_COLOURS)
    if unknown:
        print(f'  WARNING: parties in data with no PARTY_COLOURS entry: {sorted(unknown)}',
              file=sys.stderr)

    all_wards = matched + no_result

    # Strip path/borough info into separate maps so we don't duplicate the
    # geometry inside three separate per-ward records. Restricted to the
    # region so the GM page doesn't ship GB-wide polygons.
    ward_paths    = {code: w['path'] for code, w in region_wards.items()}
    borough_paths = {code: b['path'] for code, b in region_boroughs.items()}

    js = []
    js.append('const VIEWBOX = ' + json.dumps(geoms['viewBoxes'][region]) + ';')
    js.append('const WARD_PATHS = ' + json.dumps(ward_paths, separators=(',', ':')) + ';')
    js.append('const BOROUGH_PATHS = ' + json.dumps(borough_paths, separators=(',', ':')) + ';')
    js.append('const WARDS = ' + json.dumps(all_wards, separators=(',', ':')) + ';')
    js.append('const PARTY_COLOURS = ' + json.dumps(PARTY_COLOURS) + ';')
    js.append('const PARTY_DISPLAY = ' + json.dumps(PARTY_DISPLAY) + ';')
    js.append('const LEGEND_ORDER = ' + json.dumps(LEGEND_ORDER) + ';')
    js.append('const NEUTRAL_FILL = "#eaeaea";')
    js.append('')

    js.append(r'''
const SVG_NS = 'http://www.w3.org/2000/svg';

function makePath(d, cls, fill, titleText) {
  const p = document.createElementNS(SVG_NS, 'path');
  p.setAttribute('d', d);
  p.setAttribute('class', cls);
  if (fill) p.setAttribute('fill', fill);
  if (titleText) {
    const t = document.createElementNS(SVG_NS, 'title');
    t.textContent = titleText;
    p.appendChild(t);
  }
  return p;
}

function svgRoot() {
  const el = document.createElementNS(SVG_NS, 'svg');
  el.setAttribute('viewBox', VIEWBOX.join(' '));
  el.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  el.setAttribute('class', 'map-svg');
  el.setAttribute('role', 'img');
  return el;
}

function fmtTitle(w) {
  const lines = [w.b + ' · ' + w.wn];
  lines.push('2026: ' + (w.w ? (PARTY_DISPLAY[w.w] || w.w) : '(no result)'));
  if (w.pp) {
    lines.push('Prior: ' + (PARTY_DISPLAY[w.pp] || w.pp) + (w.py ? ' (' + w.py + ')' : ''));
  }
  if (w.mp === 'fuzzy') lines.push('(prior is approximate — boundary change)');
  return lines.join('\n');
}

/**
 * Render one map into the given container.
 *   fillFor(w) → colour, or null/undefined to use NEUTRAL_FILL
 *   classFor(w) → extra class on the ward path (e.g. 'fuzzy' on Before view)
 */
function renderMap(containerId, fillFor, classFor) {
  const target = document.getElementById(containerId);
  if (!target) return;
  const root = svgRoot();
  WARDS.forEach(w => {
    const d = WARD_PATHS[w.gss];
    if (!d) return;
    const fill = fillFor(w) || NEUTRAL_FILL;
    const extra = classFor ? classFor(w) : '';
    const cls = extra ? 'ward ' + extra : 'ward';
    root.appendChild(makePath(d, cls, fill, fmtTitle(w)));
  });
  Object.values(BOROUGH_PATHS).forEach(d => {
    root.appendChild(makePath(d, 'borough', null, null));
  });
  target.appendChild(root);
}

// Before — fill by prior_party (mostly 2022; Salford 2021).
// Wards with a fuzzy prior get a dashed stroke so readers can see which
// colours come from a boundary-change carry-over.
renderMap('map-before',
  w => w.pp ? PARTY_COLOURS[w.pp] : null,
  w => w.mp === 'fuzzy' ? 'fuzzy' : '');

// After — fill by 2026 winner.
renderMap('map-after',
  w => w.w ? PARTY_COLOURS[w.w] : null);

// Flips — fill ONLY where the seat changed hands; gainer's colour. Holds and
// no-result wards stay neutral grey.
renderMap('map-flips',
  w => (w.fl === true && w.w) ? PARTY_COLOURS[w.w] : null);

// Single shared legend, derived from parties actually present in the data.
const partiesPresent = new Set();
WARDS.forEach(w => {
  if (w.w)  partiesPresent.add(w.w);
  if (w.pp) partiesPresent.add(w.pp);
});
const legend = document.getElementById('map-legend');
if (legend) {
  LEGEND_ORDER.forEach(p => {
    if (!partiesPresent.has(p)) return;
    const row = document.createElement('span');
    row.className = 'swatch-row';
    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = PARTY_COLOURS[p];
    row.appendChild(swatch);
    row.appendChild(document.createTextNode(PARTY_DISPLAY[p] || p));
    legend.appendChild(row);
  });
  // Neutral grey is "did not flip" on the Flips view, "no result" on either.
  const neutral = document.createElement('span');
  neutral.className = 'swatch-row';
  const ns = document.createElement('span');
  ns.className = 'swatch';
  ns.style.background = NEUTRAL_FILL;
  neutral.appendChild(ns);
  neutral.appendChild(document.createTextNode('No flip / no result'));
  legend.appendChild(neutral);
}
''')

    new_js = '\n'.join(js)

    html = html_path.read_text()
    pattern = re.compile(re.escape(BEGIN) + r'\n.*?\n' + re.escape(END), re.DOTALL)
    found = pattern.findall(html)
    if len(found) != 1:
        raise SystemExit(
            f'Expected exactly one BEGIN/END pair in {html_path}, found {len(found)}.'
        )
    new_html = pattern.sub(lambda _m: BEGIN + '\n' + new_js + '\n' + END, html, count=1)
    html_path.write_text(new_html)

    print(f'\nSpliced {len(new_js):,} chars of generated JS into {html_path.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
