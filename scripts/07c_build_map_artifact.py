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


# TS022 (Census 2021 ethnic group, detailed) — five mutually-exclusive
# top-level shares. Surfaced in the per-ward hover tooltip alongside the
# winner/prior result so readers can see the demographic context behind
# each ward without a separate overlay.
ETH_KEYS = ('pct_white', 'pct_asian', 'pct_black', 'pct_mixed', 'pct_other_ethnic')


def _eth(r: dict) -> list | None:
    """Pack the 5 TS022 shares into a compact array [W, A, B, M, O].
    Returns None if any field is missing/null so the renderer can skip
    the block cleanly. Rounded to 1 dp — tooltip-grade precision."""
    vals = [r.get(k) for k in ETH_KEYS]
    if any(v is None for v in vals):
        return None
    return [round(float(v), 1) for v in vals]


def _inc(r: dict) -> int | None:
    """Ward mean income (£/yr, before housing) rounded to the nearest £.
    None for Scottish wards on the GB map and the handful of E&W wards
    where the name didn't bridge to the WD24 lookup — same null-handling
    pattern as _eth above."""
    v = r.get('mean_income')
    return int(round(v)) if v is not None else None


def normalise(s: str) -> str:
    """Loose name match: lowercase, strip dots, slash → space, both apostrophe
    variants → nothing, ' and ' → ' & ', drop a trailing '(...)' disambiguator
    or ', X' ONS-style suffix, collapse whitespace. Bridges the punctuation
    drift between the WD24 names in the ONS geom file and the Wikipedia-
    scraped names in results-side data (e.g. 'Dukinfield/Stalybridge' vs
    'Dukinfield Stalybridge', 'Kings Heath' vs "King's Heath", 'St Mary's'
    with curly vs straight apostrophe). The parenthetical suffix is the
    Census disambiguator carried in override targets (e.g. 'Barnes
    (Sunderland)') — WD24 itself uses no parens. The ', X' suffix handles
    ONS borough names like 'Kingston upon Hull, City of' / 'Herefordshire,
    County of' / 'Bristol, City of' that Wikipedia drops."""
    s = s.lower().replace('/', ' ').replace('.', '')
    s = s.replace("’", "").replace("'", "")
    s = s.replace(' and ', ' & ')
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s)
    s = re.sub(r'\s*,\s+[^,]+$', '', s)
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
    # County-election data — district-level winners for the 6 English county
    # councils that contested 2026. Only consumed by the "Show county council
    # elections" toggle on the GB page; GM ignores it.
    county_data_path = DATA / 'v1_county_data.json'
    county_data = (json.loads(county_data_path.read_text())
                   if region == 'gb' and county_data_path.exists() else {})

    # Surrey unitary overlay (issue #4 §4) — GB-only layer for the 81 East
    # Surrey + West Surrey wards from the inaugural 7 May 2026 elections.
    # The unitaries aren't in WD24 / LAD25 yet, so they side-channel
    # through scripts 22/23/24. Painted only on the After view (May 2026
    # winners); the Before and Flips views are silent because there is no
    # prior election under this geography.
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
    # English county councils (E10*) elect electoral divisions, not WD22/24
    # wards, so they have no geometry in ward_geoms.json by design. Exclude
    # them from the coverage check; their results are filtered out upstream
    # in 01c, so they contribute nothing to the join either. County-level
    # outlines for the Map view are a follow-up.
    ward_based_lads = {lad for lad in region_lad_codes if not lad.startswith('E10')}
    missing = ward_based_lads - geom_lads
    if missing:
        covered = len(ward_based_lads & geom_lads)
        print(f'  ! ward_geoms.json covers {covered}/{len(ward_based_lads)} '
              f'{region} ward-based councils; {len(missing)} councils have no '
              f'geometry. Re-run scripts/09_fetch_ward_boundaries.py --force.',
              file=sys.stderr)
        return

    # Restrict ward-level geometry to the region's registered councils so
    # the GM page doesn't drag the whole UK into its <script>, and the GB
    # page only renders ward fills for the councils we have results for.
    region_wards = {
        code: w for code, w in geoms['wards'].items()
        if w['lad'] in region_lad_codes
    }
    # Borough outlines: for GB, ship every council in the fetched set so
    # non-registered areas (the rest of the UK) appear as decorative
    # outlines and the registered 69 sit in real geographic context. For
    # GM, restrict to the region (10 boroughs).
    if region == 'gb':
        region_boroughs = geoms['boroughs']
    else:
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

    # Two-pass match so direct hits always win the polygon. Pass 1 resolves
    # every result that already shares its borough+ward name with a WD24
    # ward and claims that polygon. Pass 2 walks the rest through the
    # override CSV and drops any whose proxy polygon was already taken by
    # a direct match in pass 1 (e.g. Sandwell's 2024 "Bearwood" ward —
    # proxied to old "Smethwick" — collides with Sandwell's own 2024
    # "Smethwick" ward, which keeps the polygon).
    matched = []
    unmatched = []
    polygon_collisions = []
    used_codes = set()
    pending_override = []
    for r in results:
        key = f'{normalise(r["borough"])}::{normalise(r["ward"])}'
        code = geom_by_norm.get(key)
        if code is None:
            pending_override.append(r)
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
            'eth': _eth(r),
            'inc': _inc(r),
        })

    # Pass 2 — walk every result that didn't have a direct WD24 name match
    # through the override CSV (NEW → OLD ward name for the 2024-review
    # councils). Drop any whose proxy polygon was already claimed in pass 1
    # so direct hits always win.
    for r in pending_override:
        code = None
        override = overrides.get((r['lad_code'], r['ward']))
        if override is not None:
            key2 = f'{normalise(r["borough"])}::{normalise(override)}'
            code = geom_by_norm.get(key2)
        if code is None:
            unmatched.append((r['borough'], r['ward']))
            continue
        if code in used_codes:
            polygon_collisions.append((r['borough'], r['ward']))
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
            'eth': _eth(r),
            'inc': _inc(r),
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
            'eth': None, 'inc': None,
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
    # Country outlines (E / W / S) — only useful on the GB page, where the
    # reader can toggle borough outlines off and still see an unbroken UK
    # silhouette. GM is a single borough cluster; country outlines would
    # crop entirely outside its viewBox.
    country_paths = (
        {code: c['path'] for code, c in geoms.get('countries', {}).items()}
        if region == 'gb' else {}
    )

    # Pull each county-district's polygon path from the boroughs block; ship
    # the subset of paths the county overlay actually needs (47 on GB) rather
    # than relying on borough_paths (which is the same set for GB since GB
    # ships every council, but stays explicit for clarity and for the day GB
    # might restrict).
    county_paths = {
        lad: geoms['boroughs'][lad]['path']
        for lad in county_data
        if lad in geoms.get('boroughs', {})
    }
    if county_data:
        n_with_path = len(county_paths)
        n_districts = len(county_data)
        n_counties = len({d['county_lad'] for d in county_data.values()})
        print(f'county overlay: {n_with_path}/{n_districts} districts have polygons '
              f'across {n_counties} counties')

    # Surrey unitary overlay (GB only) — one record + path per ward in the
    # two new unitaries. Pending wards (Wikipedia not yet updated post-
    # election) carry winner='Pending' and paint with the Pending palette.
    surrey_paths = {
        code: c['path'] for code, c in surrey_geoms.get('unitaries', {}).items()
    }
    surrey_js = [{
        'c':  r['ward_code'],
        'l':  r['lad_code'],
        'ln': r['lad_name'],
        'n':  r['ward_name'],
        'w':  r['winner'],
        'y':  r['year'],
        'seats': r['seats_won'],
    } for r in surrey_records]
    if region == 'gb':
        n_surrey_decided = sum(1 for s in surrey_js if s['seats'])
        print(f'surrey in gb: {len(surrey_js)} (decided: {n_surrey_decided}; '
              f'pending: {len(surrey_js) - n_surrey_decided})')

    js = []
    js.append('const VIEWBOX = ' + json.dumps(geoms['viewBoxes'][region]) + ';')
    # GB exposes a second viewBox (zoomed to the registered councils) so
    # the page can toggle between the full UK and the data-coloured slice.
    # GM has nothing to crop to, so it emits null and the toggle stays hidden.
    alt = geoms['viewBoxes'].get('gb_registered') if region == 'gb' else None
    js.append('const VIEWBOX_REGISTERED = ' + json.dumps(alt) + ';')
    js.append('const WARD_PATHS = ' + json.dumps(ward_paths, separators=(',', ':')) + ';')
    js.append('const BOROUGH_PATHS = ' + json.dumps(borough_paths, separators=(',', ':')) + ';')
    js.append('const COUNTRY_PATHS = ' + json.dumps(country_paths, separators=(',', ':')) + ';')
    js.append('const COUNTY_PATHS = ' + json.dumps(county_paths, separators=(',', ':')) + ';')
    js.append('const COUNTY_DATA = ' + json.dumps(county_data, separators=(',', ':')) + ';')
    js.append('const SURREY_PATHS = ' + json.dumps(surrey_paths, separators=(',', ':')) + ';')
    js.append('const SURREY = ' + json.dumps(surrey_js, ensure_ascii=False,
                                             separators=(',', ':')) + ';')
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
  if (w.eth) {
    const [pw, pa, pb, pm, po] = w.eth;
    lines.push('Ethnicity (2021): '
      + 'White ' + pw.toFixed(1) + '% · '
      + 'Asian ' + pa.toFixed(1) + '% · '
      + 'Black ' + pb.toFixed(1) + '% · '
      + 'Mixed ' + pm.toFixed(1) + '% · '
      + 'Other ' + po.toFixed(1) + '%');
  }
  if (w.inc != null) {
    lines.push('Income (FY23, before housing): £' + w.inc.toLocaleString() + '/yr');
  }
  return lines.join('\n');
}

function fmtCountyTitle(c) {
  const lines = [c.county + ' County Council · ' + c.district];
  lines.push('2026: ' + (PARTY_DISPLAY[c.winner_2026] || c.winner_2026)
    + ' (' + c.seats_won_2026 + '/' + c.total_seats_2026 + ' seats)');
  if (c.winner_prior) {
    lines.push('Prior: ' + (PARTY_DISPLAY[c.winner_prior] || c.winner_prior) + ' (2021)');
  }
  return lines.join('\n');
}

function fmtSurreyTitle(s) {
  const lines = [s.ln + ' · ' + s.n];
  const seatEntries = Object.entries(s.seats || {}).sort((a, b) => b[1] - a[1]);
  if (seatEntries.length) {
    lines.push('2026 · seats: ' + seatEntries.map(
      ([p, n]) => (PARTY_DISPLAY[p] || p) + ' ' + n
    ).join(' · '));
  } else {
    lines.push('2026 · result pending (Wikipedia not yet updated)');
  }
  // Surface the painted-fill party for split-seat wards (e.g. 1-1 ties
  // resolved by votes in _plurality_winner) so the colour is legible.
  if (s.w && s.w !== 'Pending') {
    lines.push('Plurality: ' + (PARTY_DISPLAY[s.w] || s.w));
  }
  return lines.join('\n');
}

/**
 * Render one map into the given container.
 *   fillFor(w)      → ward colour (or null/undefined → NEUTRAL_FILL)
 *   classFor(w)     → extra class on the ward path (e.g. 'fuzzy')
 *   countyFillFor(c) → optional district-level colour for the counties
 *                      overlay (returns null/undefined to leave grey).
 *   surreyFillFor(s) → optional per-ward colour for the East/West Surrey
 *                      unitary overlay (null = skip; passing null/undefined
 *                      for this argument skips the entire layer).
 */
function renderMap(containerId, fillFor, classFor, countyFillFor, surreyFillFor) {
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
  // Counties overlay — one filled district per English two-tier county that
  // contested 2026. Hidden by default via CSS; the toggle adds .show-counties
  // to the .map-svg root to reveal. Sits ABOVE the wards (so a county fill
  // visually replaces the ward grid in those districts when toggled on) but
  // BELOW country/borough outlines (so boundaries still read).
  if (countyFillFor) {
    const ctyGroup = document.createElementNS(SVG_NS, 'g');
    ctyGroup.setAttribute('class', 'counties');
    Object.entries(COUNTY_PATHS).forEach(([lad, d]) => {
      const c = COUNTY_DATA[lad];
      if (!c) return;
      const fill = countyFillFor(c);
      if (!fill) return;
      ctyGroup.appendChild(makePath(d, 'county', fill, fmtCountyTitle(c)));
    });
    root.appendChild(ctyGroup);
  }
  // Surrey unitary overlay — paints East Surrey + West Surrey wards on top
  // of any underlying grey (no 2026 contest sat under these areas at WD24
  // level because the predecessor districts were abolished). Sits ABOVE
  // the wards/counties group but BELOW country/borough outlines, same as
  // the counties layer.
  if (surreyFillFor) {
    const surreyGroup = document.createElementNS(SVG_NS, 'g');
    surreyGroup.setAttribute('class', 'surrey');
    SURREY.forEach(s => {
      const d = SURREY_PATHS[s.c];
      if (!d) return;
      const fill = surreyFillFor(s) || NEUTRAL_FILL;
      surreyGroup.appendChild(makePath(d, 'surrey', fill, fmtSurreyTitle(s)));
    });
    root.appendChild(surreyGroup);
  }
  // Country outlines underneath the borough outlines so hiding the
  // boroughs leaves the UK silhouette intact. Only emitted on the GB page;
  // the object is empty on GM and this loop is a no-op there.
  Object.values(COUNTRY_PATHS).forEach(d => {
    root.appendChild(makePath(d, 'country', null, null));
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
  w => w.mp === 'fuzzy' ? 'fuzzy' : '',
  c => c.winner_prior ? PARTY_COLOURS[c.winner_prior] : null,
  null);  // no Surrey overlay on Before — no prior election under this geography

// After — fill by 2026 winner. Surrey unitaries paint here only.
renderMap('map-after',
  w => w.w ? PARTY_COLOURS[w.w] : null,
  null,
  c => c.winner_2026 ? PARTY_COLOURS[c.winner_2026] : null,
  s => (s.w && PARTY_COLOURS[s.w]) || null);

// Flips — fill ONLY where the seat changed hands; gainer's colour. Holds and
// no-result wards stay neutral grey.
renderMap('map-flips',
  w => (w.fl === true && w.w) ? PARTY_COLOURS[w.w] : null,
  null,
  c => (c.flipped && c.winner_2026) ? PARTY_COLOURS[c.winner_2026] : null,
  null);  // no Surrey overlay on Flips — no prior winners to compare against

// Toggle borough-outline visibility. Country outlines (E/W/S) stay drawn
// either way, so when boroughs are hidden the reader sees just the colour
// fills inside the UK silhouette. The button's label flips to show the
// destination of the next click. No-ops on GM (no button + no country
// paths to fall back on).
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

// Toggle the counties overlay (English county-council elections painted at
// constituent district level). Shown by default, mirroring the borough
// outlines pattern: aria-pressed=false means the layer is in its default
// (visible) state and clicking will hide. Only wires up if the page emits
// a button AND COUNTY_DATA is non-empty (i.e. the GB page).
const countyBtn = document.getElementById('counties-toggle');
if (countyBtn && Object.keys(COUNTY_DATA).length) {
  let hidden = false;
  const applyCounty = () => {
    document.querySelectorAll('.map-svg').forEach(svg => {
      svg.classList.toggle('no-counties', hidden);
    });
    countyBtn.setAttribute('aria-pressed', String(hidden));
    countyBtn.textContent = hidden ? 'Show county council elections' : 'Hide county council elections';
  };
  countyBtn.addEventListener('click', () => { hidden = !hidden; applyCounty(); });
  applyCounty();
}

// Toggle between the default viewBox and the registered-councils viewBox.
// Only wires up if a button exists AND the page emitted an alternate
// viewBox (i.e. the GB page). The button's label flips to show the
// destination of the next click, not the current state.
const zoomBtn = document.getElementById('zoom-toggle');
if (zoomBtn && VIEWBOX_REGISTERED) {
  const VIEWBOX_DEFAULT = VIEWBOX.slice();
  let zoomed = false;
  const apply = () => {
    const vb = (zoomed ? VIEWBOX_REGISTERED : VIEWBOX_DEFAULT).join(' ');
    document.querySelectorAll('.map-svg').forEach(svg => svg.setAttribute('viewBox', vb));
    zoomBtn.setAttribute('aria-pressed', String(zoomed));
    zoomBtn.textContent = zoomed ? 'Show full UK' : 'Zoom to contested councils';
  };
  zoomBtn.addEventListener('click', () => { zoomed = !zoomed; apply(); });
  apply();
}

// Single shared legend, derived from parties actually present in the data.
const partiesPresent = new Set();
WARDS.forEach(w => {
  if (w.w)  partiesPresent.add(w.w);
  if (w.pp) partiesPresent.add(w.pp);
});
SURREY.forEach(s => { if (s.w && s.w !== 'Pending') partiesPresent.add(s.w); });
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
