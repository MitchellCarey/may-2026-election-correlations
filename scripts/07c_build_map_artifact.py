"""Splice the generated data + map renderer JS into docs/map.html.

Mirror of scripts/07b_build_changes_artifact.py for the Map page. Reads:

  - data/all_wards_with_prior.json (214 ward records: borough, ward,
    winner, prior_party, flipped, match_type_prior, ...)
  - data/ward_geoms.json           (215 ward polygons + 10 borough outlines,
    pre-projected to BNG and emitted as SVG path strings — see scripts/09)

…joins them via normalised borough+ward name (the geom file is the source of
truth for the WD24 names), and rewrites the block between the BEGIN/END
markers in docs/map.html in place.

Wards present in the geom set but missing from results data (Bury::Moorside,
whose election was cancelled) are still rendered, in neutral grey on every
view. Aborts if any results-side ward fails to join — drift in either
dataset must be investigated, not silently dropped.
"""
import json
import re
import sys
from pathlib import Path

from _artifact_lib import (
    PARTY_COLOURS_MAP as PARTY_COLOURS,
    PARTY_DISPLAY_MAP as PARTY_DISPLAY,
    LEGEND_ORDER_MAP as LEGEND_ORDER,
)
from _councils import lad_codes_for

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

GM_LAD_CODES = lad_codes_for('gm')

BEGIN = "// ===== BEGIN GENERATED — see scripts/07c_build_map_artifact.py ====="
END = "// ===== END GENERATED ====="


def normalise(s: str) -> str:
    """Loose name match: lowercase, strip dots, slash → space, ' and ' → ' & ',
    collapse whitespace. Bridges the punctuation drift between the WD24 names
    in the ONS geom file and the human-edited names in results-side data
    (e.g. 'Dukinfield/Stalybridge' vs 'Dukinfield Stalybridge')."""
    s = s.lower().replace('/', ' ').replace('.', '')
    s = s.replace(' and ', ' & ')
    return ' '.join(s.split())


def main():
    with open(DATA / 'all_wards_with_prior.json') as f:
        results = json.load(f)
    with open(DATA / 'ward_geoms.json') as f:
        geoms = json.load(f)

    # Phase B transitional filter — results is now GB-wide but ward_geoms.json
    # is still GM-only (09 has its own GM filter). Restrict to GM until
    # both sides align in Phase B.10 / C.13.
    results = [r for r in results if r.get('lad_code') in GM_LAD_CODES]

    # Normalised name → WD24CD lookup; geom file is the source of truth.
    geom_by_norm = {}
    for code, w in geoms['wards'].items():
        borough_name = geoms['boroughs'][w['lad']]['name']
        geom_by_norm[f'{normalise(borough_name)}::{normalise(w["name"])}'] = code

    matched = []
    unmatched = []
    used_codes = set()
    for r in results:
        key = f'{normalise(r["borough"])}::{normalise(r["ward"])}'
        code = geom_by_norm.get(key)
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
    for code, w in geoms['wards'].items():
        if code in used_codes:
            continue
        borough_name = geoms['boroughs'][w['lad']]['name']
        no_result.append({
            'gss': code, 'b': borough_name, 'wn': w['name'],
            'w': None, 'pp': None, 'py': None, 'fl': None, 'mp': None,
        })

    print(f'matched: {len(matched)}/{len(results)} results-side wards joined to a polygon')
    if unmatched:
        for b, w in unmatched:
            print(f'  [UNMATCHED] {b} :: {w}', file=sys.stderr)
        sys.exit(1)
    no_result_names = ', '.join(f'{w["b"]}::{w["wn"]}' for w in no_result)
    print(f'no-result polygons (rendered grey): {len(no_result)}'
          + (f' — {no_result_names}' if no_result else ''))
    print(f'total polygons in WARDS: {len(matched) + len(no_result)}/215')

    # Surface any party in the data that we don't have a colour for — the
    # renderer would silently fall back to NEUTRAL_FILL otherwise.
    parties_in_data = {w['w'] for w in matched if w['w']} | {w['pp'] for w in matched if w['pp']}
    unknown = parties_in_data - set(PARTY_COLOURS)
    if unknown:
        print(f'  WARNING: parties in data with no PARTY_COLOURS entry: {sorted(unknown)}',
              file=sys.stderr)

    all_wards = matched + no_result

    # Strip path/borough info into separate maps so we don't duplicate the
    # ~134 KB of geometry inside three separate per-ward records.
    ward_paths    = {code: w['path'] for code, w in geoms['wards'].items()}
    borough_paths = {code: w['path'] for code, w in geoms['boroughs'].items()}

    js = []
    js.append('const VIEWBOX = ' + json.dumps(geoms['viewBox']) + ';')
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

    html_path = DOCS / 'map.html'
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
