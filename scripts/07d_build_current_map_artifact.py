"""Splice the generated data + map renderer JS into docs/current.html (or
docs/uk/current.html when --region=gb).

Sibling to scripts/07c_build_map_artifact.py but for the Current map page:
one map (no Before/After/Flips), painted by the most-recent winner of each
ward, regardless of election year.

Reads:
  - data/current_winners.json   (per-ward records produced by 04c — one
                                  record per GB-ward-based polygon, with
                                  winner/year/source/match_type)
  - data/ward_geoms.json         (GB-wide ward + council polygons, plus
                                  per-region viewBox spec)

Filters to --region:
  - gm: just the 10 Greater Manchester boroughs (via _councils.lad_codes_for)
  - gb: every GB ward-based LAD present in the geom file (derived directly
        from ward_geoms.json so coverage isn't constrained by the registry —
        the Current page is *meant* to render every ward, even ones where
        the council hasn't been added to councils.yaml yet; those simply
        show as grey).

Rewrites the block between the BEGIN/END markers in the target page.
"""
import argparse
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

BEGIN = "// ===== BEGIN GENERATED — see scripts/07d_build_current_map_artifact.py ====="
END = "// ===== END GENERATED ====="

# Match 04c — GB-only LAD prefixes, NI excluded.
GB_LAD_PREFIXES = ('E06', 'E07', 'E08', 'E09', 'W06', 'S12')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--region', default='gm', choices=['gm', 'gb'])
    args = ap.parse_args()
    region = args.region
    html_path = DOCS / 'current.html' if region == 'gm' else DOCS / 'uk' / 'current.html'

    with open(DATA / 'current_winners.json') as f:
        records = json.load(f)
    with open(DATA / 'ward_geoms.json') as f:
        geoms = json.load(f)

    if region not in geoms.get('viewBoxes', {}):
        print(f'  ! ward_geoms.json has no viewBox for region={region!r} '
              f'(found: {sorted(geoms.get("viewBoxes", {}))}). '
              f'Re-run scripts/09_fetch_ward_boundaries.py --force.',
              file=sys.stderr)
        return

    # Region filter — GM uses the registry, GB takes every GB-prefixed LAD
    # in the geom file so coverage isn't blocked on registry expansion.
    if region == 'gm':
        region_lads = lad_codes_for('gm')
    else:
        region_lads = {lad for lad in geoms['boroughs'] if lad.startswith(GB_LAD_PREFIXES)}

    region_records = [r for r in records if r['lad_code'] in region_lads]
    region_wards = {
        code: w for code, w in geoms['wards'].items()
        if w['lad'] in region_lads
    }
    region_boroughs = {
        code: b for code, b in geoms['boroughs'].items()
        if code in region_lads
    }
    # On GB, also surface every non-region GB borough as a decorative outline so
    # contested-and-uncontested areas sit in real geographic context. This is
    # the same convention as 07c (it ships every borough on the GB page).
    if region == 'gb':
        region_boroughs = {
            code: b for code, b in geoms['boroughs'].items()
            if code.startswith(GB_LAD_PREFIXES)
        }

    # Compact per-ward records keyed by gss — only fields the renderer needs.
    wards_js = [{
        'gss': r['gss'],
        'b':   r['borough'],
        'wn':  r['ward'],
        'w':   r['winner'],
        'y':   r['year'],
    } for r in region_records]

    # Coverage report
    n_total = len(wards_js)
    n_winner = sum(1 for w in wards_js if w['w'])
    print(f'wards in {region} region: {n_total} (with winner: {n_winner}; grey: {n_total - n_winner})')

    parties_in_data = {w['w'] for w in wards_js if w['w']}
    unknown = parties_in_data - set(PARTY_COLOURS)
    if unknown:
        print(f'  WARNING: parties with no PARTY_COLOURS entry: {sorted(unknown)}',
              file=sys.stderr)

    ward_paths    = {code: w['path'] for code, w in region_wards.items()}
    borough_paths = {code: b['path'] for code, b in region_boroughs.items()}
    country_paths = (
        {code: c['path'] for code, c in geoms.get('countries', {}).items()}
        if region == 'gb' else {}
    )

    js = []
    js.append('const VIEWBOX = ' + json.dumps(geoms['viewBoxes'][region]) + ';')
    js.append('const WARD_PATHS = ' + json.dumps(ward_paths, separators=(',', ':')) + ';')
    js.append('const BOROUGH_PATHS = ' + json.dumps(borough_paths, separators=(',', ':')) + ';')
    js.append('const COUNTRY_PATHS = ' + json.dumps(country_paths, separators=(',', ':')) + ';')
    js.append('const WARDS = ' + json.dumps(wards_js, separators=(',', ':')) + ';')
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
  if (w.w) {
    lines.push('Last election: ' + (w.y ? w.y + ' · ' : '')
      + 'winner: ' + (PARTY_DISPLAY[w.w] || w.w));
  } else {
    lines.push('(no current-control data)');
  }
  return lines.join('\n');
}

// Render the one Current-control map.
const target = document.getElementById('map-current');
if (target) {
  const root = svgRoot();
  WARDS.forEach(w => {
    const d = WARD_PATHS[w.gss];
    if (!d) return;
    const fill = (w.w && PARTY_COLOURS[w.w]) || NEUTRAL_FILL;
    root.appendChild(makePath(d, 'ward', fill, fmtTitle(w)));
  });
  // Country outlines first so toggling boroughs off still shows the UK
  // silhouette on GB. Empty on GM (no country paths shipped).
  Object.values(COUNTRY_PATHS).forEach(d => {
    root.appendChild(makePath(d, 'country', null, null));
  });
  Object.values(BOROUGH_PATHS).forEach(d => {
    root.appendChild(makePath(d, 'borough', null, null));
  });
  target.appendChild(root);
}

// Borough-outline toggle (GB only — gated on COUNTRY_PATHS being non-empty
// so removing borough outlines still leaves a sensible silhouette).
const boroughBtn = document.getElementById('borough-toggle');
if (boroughBtn && Object.keys(COUNTRY_PATHS).length) {
  let hidden = false;
  const applyBorough = () => {
    document.querySelectorAll('.map-svg').forEach(svg => {
      svg.classList.toggle('no-boroughs', hidden);
    });
    boroughBtn.setAttribute('aria-pressed', String(hidden));
    boroughBtn.textContent = hidden ? 'Show borough outlines' : 'Hide borough outlines';
  };
  boroughBtn.addEventListener('click', () => { hidden = !hidden; applyBorough(); });
  applyBorough();
}

// Shared legend, derived from parties actually present.
const partiesPresent = new Set();
WARDS.forEach(w => { if (w.w) partiesPresent.add(w.w); });
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
  const neutral = document.createElement('span');
  neutral.className = 'swatch-row';
  const ns = document.createElement('span');
  ns.className = 'swatch';
  ns.style.background = NEUTRAL_FILL;
  neutral.appendChild(ns);
  neutral.appendChild(document.createTextNode('No current-control data'));
  legend.appendChild(neutral);
}
''')

    new_js = '\n'.join(js)

    if not html_path.exists():
        print(f'  ! {html_path.relative_to(ROOT)} does not exist yet — '
              f'create it from docs/uk/map.html\'s shape with a BEGIN/END '
              f'splice block. Skipping splice.', file=sys.stderr)
        return

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
