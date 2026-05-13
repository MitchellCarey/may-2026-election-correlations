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
    ced_path = DATA / 'ced_winners.json'
    ced_records = json.loads(ced_path.read_text()) if ced_path.exists() else []
    holyrood_path = DATA / 'holyrood_winners.json'
    holyrood_records = json.loads(holyrood_path.read_text()) if holyrood_path.exists() else []
    # Senedd 2026 overlay — GB-only layer that paints all of Wales by the
    # plurality party of each Senedd constituency. Skipped on GM (no
    # Welsh polygons in the GM viewBox) and when the data files don't
    # exist (so a partial pipeline run doesn't break the renderer).
    senedd_path = DATA / 'senedd_2026.json'
    senedd_geom_path = DATA / 'senedd_geoms.json'
    senedd_records = (
        json.loads(senedd_path.read_text())
        if region == 'gb' and senedd_path.exists() else []
    )
    senedd_geoms = (
        json.loads(senedd_geom_path.read_text())
        if region == 'gb' and senedd_geom_path.exists() else {'constituencies': {}}
    )
    # GE 2024 (Westminster) overlay — GB-only layer that paints every
    # constituency by its 4 July 2024 winner. Same gating as Senedd: NI
    # is fetched on disk but filtered out at render time because the gb
    # viewBox excludes NI. The two JSONs being absent is benign — the
    # arrays come out empty and the view picker simply doesn't surface
    # the "GE 2024 only" button.
    pcon_path = DATA / 'ge2024.json'
    pcon_geom_path = DATA / 'pcon_geoms.json'
    pcon_records = (
        json.loads(pcon_path.read_text())
        if region == 'gb' and pcon_path.exists() else []
    )
    pcon_geoms = (
        json.loads(pcon_geom_path.read_text())
        if region == 'gb' and pcon_geom_path.exists() else {'constituencies': {}}
    )
    # NI codes filtered out here so the rest of 07d (and the JS bundle) only
    # sees the 632 GB seats. England=E14, Wales=W07, Scotland=S14.
    GB_PCON_PREFIXES = ('E14', 'W07', 'S14')
    pcon_records = [r for r in pcon_records if r['code'].startswith(GB_PCON_PREFIXES)]

    # Surrey unitary overlay (issue #4 §4) — GB-only layer that paints the
    # 36 East Surrey + 45 West Surrey wards from the inaugural 7 May 2026
    # elections. The unitaries aren't in WD24 / LAD25 yet (administrative
    # effect 1 April 2027), so they side-channel through scripts 22/23/24
    # rather than the main councils.yaml pipeline. Synthetic LAD codes
    # XSE / XSW; ward polygons sourced from the LGBCE Surrey post-review
    # final-recommendation shapefile.
    surrey_path = DATA / 'surrey_2026.json'
    surrey_geom_path = DATA / 'surrey_geoms.json'
    surrey_records = (
        json.loads(surrey_path.read_text())
        if region == 'gb' and surrey_path.exists() else []
    )
    surrey_geoms = (
        json.loads(surrey_geom_path.read_text())
        if region == 'gb' and surrey_geom_path.exists() else {'unitaries': {}}
    )

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
    # cc/cn/cw/cy = parent-CED county / name / winner / year, populated only
    # for wards in 2-tier English districts (issue #8 acceptance 3 quick-win).
    wards_js = []
    for r in region_records:
        rec = {
            'gss': r['gss'],
            'b':   r['borough'],
            'wn':  r['ward'],
            'w':   r['winner'],
            'y':   r['year'],
        }
        if r.get('ced_county'):
            rec['cc'] = r['ced_county']
            rec['cn'] = r['ced_name']
            rec['cw'] = r['ced_winner']
            rec['cy'] = r['ced_year']
        wards_js.append(rec)

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

    # CED-level data + polygons for the county-council layer toggle. Only
    # populated on the GB page — the GM map has no E10 county-council overlap
    # (all 10 GM boroughs are single-tier metropolitan, no CEDs sit over them).
    ced_paths: dict = {}
    ceds_js: list = []
    holyrood_paths: dict = {}
    holyrood_js: list = []
    if region == 'gb':
        all_ceds = geoms.get('ceds', {})
        ced_paths = {code: c['path'] for code, c in all_ceds.items()}
        ceds_js = [{
            'ced':  r['ced'],
            'n':    r['name'],
            'c':    r['county'],
            'w':    r['winner'],
            'y':    r['year'],
        } for r in ced_records]
        n_ced_winner = sum(1 for c in ceds_js if c['w'])
        print(f'ceds in gb: {len(ceds_js)} (with winner: {n_ced_winner}; '
              f'grey: {len(ceds_js) - n_ced_winner})')

        # Holyrood 2026 constituencies (issue #21). Same GB-only gate as CEDs:
        # the SPC layer only paints over Scotland, which the GM map doesn't show.
        all_spcs = geoms.get('spcs', {})
        holyrood_paths = {code: s['path'] for code, s in all_spcs.items()}
        holyrood_js = [{
            'spc':  r['spc'],
            'n':    r['name'],
            'w':    r['winner'],
            'y':    r['year'],
        } for r in holyrood_records]
        n_h_winner = sum(1 for h in holyrood_js if h['w'])
        print(f'holyrood spcs in gb: {len(holyrood_js)} (with winner: {n_h_winner}; '
              f'grey: {len(holyrood_js) - n_h_winner})')

    # Senedd 2026 overlay (GB only) — one record + path per constituency,
    # painted by plurality party with the 6-seat split in the tooltip.
    senedd_paths: dict = {
        code: c['path'] for code, c in senedd_geoms.get('constituencies', {}).items()
    }
    senedd_js = [{
        's':     r['code'],
        'n':     r['name'],
        'w':     r['plurality_party'],
        'y':     r['year'],
        'seats': r['seats'],
        'votes': r['votes'],
    } for r in senedd_records]
    if region == 'gb':
        n_senedd_winner = sum(1 for s in senedd_js if s['w'])
        print(f'senedd in gb: {len(senedd_js)} (with winner: {n_senedd_winner}; '
              f'grey: {len(senedd_js) - n_senedd_winner})')

    # GE 2024 overlay (GB only) — one record + path per Westminster
    # constituency, painted by 2024 GE winner with the candidate name in the
    # tooltip. Pre-filtered to GB above.
    pcon_paths: dict = {
        code: c['path']
        for code, c in pcon_geoms.get('constituencies', {}).items()
        if code.startswith(GB_PCON_PREFIXES)
    }
    pcon_js = [{
        'p': r['code'],
        'n': r['name'],
        'w': r['winner_party'],
        'c': r['candidate'],
        'y': r['year'],
    } for r in pcon_records]
    if region == 'gb':
        n_pcon_winner = sum(1 for p in pcon_js if p['w'])
        print(f'pcon in gb: {len(pcon_js)} (with winner: {n_pcon_winner}; '
              f'grey: {len(pcon_js) - n_pcon_winner})')

    # Surrey unitary overlay (GB only) — one record + path per ward in the
    # two new unitaries, painted by 2026 plurality with seats + votes in
    # the tooltip. "Pending" wards (where Wikipedia hasn't been updated
    # post-election) paint with the Pending palette colour.
    surrey_paths: dict = {
        code: c['path'] for code, c in surrey_geoms.get('unitaries', {}).items()
    }
    surrey_js = [{
        'c':     r['ward_code'],
        'l':     r['lad_code'],
        'ln':    r['lad_name'],
        'n':     r['ward_name'],
        'w':     r['winner'],
        'y':     r['year'],
        'seats': r['seats_won'],
        'votes': r['votes'],
    } for r in surrey_records]
    if region == 'gb':
        n_surrey_decided = sum(1 for s in surrey_js if s['seats'])
        print(f'surrey in gb: {len(surrey_js)} (decided: {n_surrey_decided}; '
              f'pending: {len(surrey_js) - n_surrey_decided})')

    js = []
    js.append('const VIEWBOX = ' + json.dumps(geoms['viewBoxes'][region]) + ';')
    js.append('const WARD_PATHS = ' + json.dumps(ward_paths, separators=(',', ':')) + ';')
    js.append('const BOROUGH_PATHS = ' + json.dumps(borough_paths, separators=(',', ':')) + ';')
    js.append('const COUNTRY_PATHS = ' + json.dumps(country_paths, separators=(',', ':')) + ';')
    js.append('const CED_PATHS = ' + json.dumps(ced_paths, separators=(',', ':')) + ';')
    js.append('const HOLYROOD_PATHS = ' + json.dumps(holyrood_paths, separators=(',', ':')) + ';')
    js.append('const SENEDD_PATHS = ' + json.dumps(senedd_paths, separators=(',', ':')) + ';')
    js.append('const PCON_PATHS = ' + json.dumps(pcon_paths, separators=(',', ':')) + ';')
    js.append('const SURREY_PATHS = ' + json.dumps(surrey_paths, separators=(',', ':')) + ';')
    js.append('const WARDS = ' + json.dumps(wards_js, separators=(',', ':')) + ';')
    js.append('const CEDS = ' + json.dumps(ceds_js, separators=(',', ':')) + ';')
    js.append('const HOLYROOD = ' + json.dumps(holyrood_js, separators=(',', ':')) + ';')
    js.append('const SENEDD = ' + json.dumps(senedd_js, ensure_ascii=False,
                                             separators=(',', ':')) + ';')
    js.append('const PCON = ' + json.dumps(pcon_js, ensure_ascii=False,
                                           separators=(',', ':')) + ';')
    js.append('const SURREY = ' + json.dumps(surrey_js, ensure_ascii=False,
                                             separators=(',', ':')) + ';')
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
  if (w.cc) {
    const base = 'County Council · ' + w.cc + ' · ' + w.cn;
    if (w.cw) {
      lines.push(base + ' · ' + (w.cy ? w.cy + ' · ' : '')
        + 'winner: ' + (PARTY_DISPLAY[w.cw] || w.cw));
    } else {
      lines.push(base + ' · (no county-council data on record)');
    }
  }
  return lines.join('\n');
}

function fmtCedTitle(c) {
  const lines = [c.c + ' County Council · ' + c.n];
  if (c.w) {
    lines.push((c.y ? c.y + ' · ' : '') + 'winner: ' + (PARTY_DISPLAY[c.w] || c.w));
  } else {
    lines.push('(no county-council data on record)');
  }
  return lines.join('\n');
}

function fmtHolyroodTitle(h) {
  const lines = ['Scottish Parliament · ' + h.n];
  if (h.w) {
    lines.push((h.y ? h.y + ' · ' : '') + 'winner: ' + (PARTY_DISPLAY[h.w] || h.w));
  } else {
    lines.push('(no constituency result on record)');
  }
  return lines.join('\n');
}

function fmtSeneddTitle(s) {
  const lines = ['Senedd · ' + s.n];
  const seatEntries = Object.entries(s.seats || {}).sort((a, b) => b[1] - a[1]);
  if (seatEntries.length) {
    lines.push(s.y + ' · seats: ' + seatEntries.map(
      ([p, n]) => (PARTY_DISPLAY[p] || p) + ' ' + n
    ).join(' · '));
  }
  if (s.w) {
    lines.push('Plurality: ' + (PARTY_DISPLAY[s.w] || s.w));
  }
  return lines.join('\n');
}

function fmtPconTitle(p) {
  const lines = ['Westminster · ' + p.n];
  if (p.w) {
    lines.push((p.y ? p.y + ' · ' : '') + 'winner: ' + (PARTY_DISPLAY[p.w] || p.w)
               + (p.c ? ' (' + p.c + ')' : ''));
  } else {
    lines.push('(no GE 2024 result on record)');
  }
  return lines.join('\n');
}

function fmtSurreyTitle(s) {
  const lines = [s.ln + ' · ' + s.n];
  const seatEntries = Object.entries(s.seats || {}).sort((a, b) => b[1] - a[1]);
  if (seatEntries.length) {
    lines.push(s.y + ' · seats: ' + seatEntries.map(
      ([p, n]) => (PARTY_DISPLAY[p] || p) + ' ' + n
    ).join(' · '));
  } else {
    lines.push(s.y + ' · result pending (Wikipedia not yet updated)');
  }
  if (s.w && s.w !== 'Pending') {
    lines.push('Plurality: ' + (PARTY_DISPLAY[s.w] || s.w));
  }
  return lines.join('\n');
}

// Render the one Current-control map. Ward + CED + Holyrood + Senedd + PCON
// fills are interleaved into a single layer in chronological order — older
// elections paint first, newer ones on top — so the topmost visible polygon
// at every point shows whichever vote was most recent. CSS view-class
// toggles (.view-recent / .view-wards / .view-ceds / .view-holyrood /
// .view-senedd / .view-pcon) gate per-path visibility for the picker below.
const target = document.getElementById('map-current');
if (target) {
  const root = svgRoot();
  // Combine ward + CED + Holyrood + Senedd + PCON records into one list.
  // Sort ascending by year so newer elections paint last (= on top in SVG
  // paint order). Within a year, wards beat CEDs (more granular district
  // vs. county); Holyrood and Senedd beat both (Holyrood paints Scotland,
  // Senedd paints Wales — no overlap with each other, but treat them as
  // the most specific layer so the order is deterministic). PCON (GE 2024
  // = year 2024) sits between wards and Holyrood/Senedd in the KIND_ORDER
  // tiebreak but the year sort puts it below 2025 CEDs and 2026 devolved
  // layers regardless. Records with y=null sort to the bottom (treated
  // as oldest).
  const KIND_ORDER = { ced: 0, ward: 1, surrey: 2, pcon: 3, holyrood: 4, senedd: 5 };
  const items = [
    ...WARDS.map(w => ({ kind: 'ward', d: WARD_PATHS[w.gss], y: w.y,
                         fill: (w.w && PARTY_COLOURS[w.w]) || NEUTRAL_FILL,
                         title: fmtTitle(w) })),
    ...CEDS.map(c => ({  kind: 'ced',  d: CED_PATHS[c.ced], y: c.y,
                         fill: (c.w && PARTY_COLOURS[c.w]) || NEUTRAL_FILL,
                         title: fmtCedTitle(c) })),
    ...HOLYROOD.map(h => ({ kind: 'holyrood', d: HOLYROOD_PATHS[h.spc], y: h.y,
                            fill: (h.w && PARTY_COLOURS[h.w]) || NEUTRAL_FILL,
                            title: fmtHolyroodTitle(h) })),
    ...SENEDD.map(s => ({ kind: 'senedd', d: SENEDD_PATHS[s.s], y: s.y,
                          fill: (s.w && PARTY_COLOURS[s.w]) || NEUTRAL_FILL,
                          title: fmtSeneddTitle(s) })),
    ...PCON.map(p => ({ kind: 'pcon', d: PCON_PATHS[p.p], y: p.y,
                        fill: (p.w && PARTY_COLOURS[p.w]) || NEUTRAL_FILL,
                        title: fmtPconTitle(p) })),
    ...SURREY.map(s => ({ kind: 'surrey', d: SURREY_PATHS[s.c], y: s.y,
                          fill: (s.w && PARTY_COLOURS[s.w]) || NEUTRAL_FILL,
                          title: fmtSurreyTitle(s) })),
  ].filter(it => it.d);
  items.sort((a, b) => (a.y ?? 0) - (b.y ?? 0) || (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]));
  const fills = document.createElementNS(SVG_NS, 'g');
  fills.setAttribute('class', 'fills');
  items.forEach(it => fills.appendChild(makePath(it.d, it.kind, it.fill, it.title)));
  root.appendChild(fills);

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

// View picker (GB only — gated on CEDS / HOLYROOD / SENEDD / PCON being
// non-empty). Six buttons with data-view attributes flip the SVG root
// between .view-recent (default; chronological z-order), .view-wards
// (only ward polygons), .view-ceds (only CED polygons), .view-holyrood
// (only Holyrood SPCs), .view-senedd (only Senedd constituencies), and
// .view-pcon (only GE 2024 PCONs). DOM is built once; CSS does the
// per-mode hiding.
const VIEWS = ['recent', 'wards', 'ceds', 'holyrood', 'senedd', 'pcon', 'surrey'];
const setView = name => {
  document.querySelectorAll('.map-svg').forEach(svg => {
    VIEWS.forEach(v => svg.classList.toggle('view-' + v, v === name));
  });
  document.querySelectorAll('[data-view]').forEach(btn => {
    btn.setAttribute('aria-pressed', String(btn.dataset.view === name));
  });
};
if (CEDS.length || HOLYROOD.length || SENEDD.length || PCON.length || SURREY.length) {
  document.querySelectorAll('[data-view]').forEach(btn => {
    btn.addEventListener('click', () => setView(btn.dataset.view));
  });
  setView('recent');
}

// Shared legend, derived from parties actually present.
const partiesPresent = new Set();
WARDS.forEach(w => { if (w.w) partiesPresent.add(w.w); });
HOLYROOD.forEach(h => { if (h.w) partiesPresent.add(h.w); });
SENEDD.forEach(s => { if (s.w) partiesPresent.add(s.w); });
PCON.forEach(p => { if (p.w) partiesPresent.add(p.w); });
SURREY.forEach(s => { if (s.w) partiesPresent.add(s.w); });
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
