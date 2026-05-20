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
    # Pre-2026 Senedd polygons + per-constituency + per-region history
    # (issue #69 phase 1D / #72). The 40-seat NAWC21 layout was in legal
    # effect at the 2016 + 2021 elections; the 16-seat S0x layout came in
    # for 2026. era="pre"/"post" gating in paintAtYear toggles which
    # polygon set is visible based on the slider year.
    senedd_geom_2007_path = DATA / 'senedd_geoms_2007.json'
    senedd_history_path = DATA / 'senedd_history.json'
    senedd_geoms_2007 = (
        json.loads(senedd_geom_2007_path.read_text())
        if region == 'gb' and senedd_geom_2007_path.exists() else {'constituencies': {}}
    )
    senedd_history = (
        json.loads(senedd_history_path.read_text())
        if region == 'gb' and senedd_history_path.exists()
        else {'years': [], 'constituencies': {}, 'regions': {}}
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
    # Pre-review PCON polygons + per-PCON history (issue #69 phase 1E / #71).
    # The 2010-era boundary set (PCON_DEC_2021 = identical geometry to the
    # boundaries in legal effect at the 2015 / 2017 / 2019 elections; ONS
    # snapshot date is December 2021) and the per-PCON × per-year winners
    # sourced from House of Commons Library CBP-8647 (the authoritative
    # academic-grade source — see CLAUDE.md "Data accuracy is paramount").
    # Era='pre'/'post' gating in paintAtYear toggles which polygon set is
    # visible based on the slider year, with the boundary at 2024 (the
    # July 2024 review).
    pcon_2010_geom_path = DATA / 'pcon_geoms_2010.json'
    pcon_history_path = DATA / 'ge_history.json'
    pcon_geoms_2010 = (
        json.loads(pcon_2010_geom_path.read_text())
        if region == 'gb' and pcon_2010_geom_path.exists() else {'constituencies': {}}
    )
    ge_history = (
        json.loads(pcon_history_path.read_text())
        if region == 'gb' and pcon_history_path.exists()
        else {'years': [], 'pcons': {}}
    )
    # NI codes filtered out here so the rest of 07d (and the JS bundle) only
    # sees the 632 GB seats. England=E14, Wales=W07, Scotland=S14 for the
    # 2024 boundary set; the 2010 set used N06 for NI (codes are largely
    # disjoint from PCON24CD; only 5 unchanged Scottish constituencies
    # overlap).
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

    # Ward history (issue #70 phase 1A) — GB-only. Drives the time slider
    # below the legend, letting readers scrub 2018→2026. Missing file is
    # benign: the slider chrome is hidden when WARD_HISTORY is empty.
    history_path = DATA / 'ward_history.json'
    ward_history = (
        json.loads(history_path.read_text())
        if region == 'gb' and history_path.exists() else {'years': [], 'wards': {}}
    )

    # CED history (issue #69 phase 1B / #73) — GB-only. Per-CED per-year
    # winners for the county-tier slider repaint. Polygon keys come from
    # both `ceds` (current era) and `ceds_pre_review` (PRE_ keys for
    # Norfolk/Essex/Suffolk/Surrey 2017+2021 boundaries). Missing file is
    # benign: paintAtYear silently leaves CED fills at their initial values.
    ced_history_path = DATA / 'ced_history.json'
    ced_history = (
        json.loads(ced_history_path.read_text())
        if region == 'gb' and ced_history_path.exists() else {'years': [], 'ceds': {}}
    )

    # Holyrood history (issue #69 phase 1C / #74) — GB-only. Per-SPC per-year
    # winners for the Holyrood slider repaint. Polygon keys come from both
    # `spcs` (current SPC26 codes for 2026) and `spcs_pre_review` (PRE_<SPC22CD>
    # for the 2014 boundary set used at 2016+2021). Missing file is benign:
    # paintAtYear silently leaves Holyrood fills at their initial values.
    holyrood_history_path = DATA / 'holyrood_history.json'
    holyrood_history = (
        json.loads(holyrood_history_path.read_text())
        if region == 'gb' and holyrood_history_path.exists() else {'years': [], 'spcs': {}}
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
    #
    # Phase 1B (#73) adds a parallel `ceds_pre_review` polygon set for the
    # four counties whose 2017+2021 boundaries differ from 2025/2026
    # (Norfolk/Essex/Suffolk: replaced by LGBCE for 2026; Surrey: abolished
    # April 2027). Each CED path is stamped with a `data-era` attribute so
    # paintAtYear can show/hide based on slider year:
    #   'pre'  → visible at year <  2026 (PRE_ keys)
    #   'post' → visible at year >= 2026 (LGBCE_ keys for the 3 reviewed counties)
    #   'any'  → always visible (bare CED25CDs in the 17 unchanged counties)
    ced_paths: dict = {}
    ced_paths_pre: dict = {}
    ced_eras: dict = {}
    ceds_js: list = []
    holyrood_paths: dict = {}
    holyrood_paths_pre: dict = {}
    holyrood_eras: dict = {}
    holyrood_js: list = []
    if region == 'gb':
        all_ceds = geoms.get('ceds', {})
        all_ceds_pre = geoms.get('ceds_pre_review', {})
        ced_paths = {code: c['path'] for code, c in all_ceds.items()}
        ced_paths_pre = {code: c['path'] for code, c in all_ceds_pre.items()}
        for code in all_ceds:
            ced_eras[code] = 'post' if code.startswith('LGBCE_') else 'any'
        for code in all_ceds_pre:
            ced_eras[code] = 'pre'
        ceds_js = [{
            'ced':  r['ced'],
            'n':    r['name'],
            'c':    r['county'],
            'w':    r['winner'],
            'y':    r['year'],
        } for r in ced_records]
        # Synthetic CEDS records for the pre-review polygons. They don't
        # appear in ced_winners.json (04c only joins to `ceds`), but they
        # still need DOM elements rendered so paintAtYear can light them
        # up at year < 2026. Initial fill = grey; winner/year come from
        # CED_HISTORY at slider time. The renderer's chronological sort
        # places them at the bottom (y=null) — fine because they're
        # hidden at the initial slider position (year=2026).
        pre_meta_by_key = ced_history.get('ceds', {}) if region == 'gb' else {}
        for key, meta in all_ceds_pre.items():
            ceds_js.append({
                'ced': key,
                'n':   meta.get('name', ''),
                'c':   pre_meta_by_key.get(key, {}).get('county', meta.get('cty_name', '')),
                'w':   None,
                'y':   None,
            })
        n_ced_winner = sum(1 for c in ceds_js if c['w'])
        print(f'ceds in gb: {len(ceds_js)} (with winner: {n_ced_winner}; '
              f'grey: {len(ceds_js) - n_ced_winner}; '
              f'incl. {len(all_ceds_pre)} pre-review polygons hidden at year >= 2026)')

        # Holyrood 2026 constituencies (issue #21). Same GB-only gate as CEDs:
        # the SPC layer only paints over Scotland, which the GM map doesn't show.
        #
        # Phase 1C (#74) adds the pre-review polygon set (SPC22, used at the
        # 2016 + 2021 elections) under `spcs_pre_review`. Era classification
        # mirrors the CED layer:
        #   'pre'  → visible at year <  2026 (PRE_<SPC22CD>; 2014 boundary set)
        #   'post' → visible at year >= 2026 (bare S16000***; 2026 review)
        all_spcs = geoms.get('spcs', {})
        all_spcs_pre = geoms.get('spcs_pre_review', {})
        holyrood_paths = {code: s['path'] for code, s in all_spcs.items()}
        holyrood_paths_pre = {code: s['path'] for code, s in all_spcs_pre.items()}
        for code in all_spcs:
            holyrood_eras[code] = 'post'
        for code in all_spcs_pre:
            holyrood_eras[code] = 'pre'
        holyrood_js = [{
            'spc':  r['spc'],
            'n':    r['name'],
            'w':    r['winner'],
            'y':    r['year'],
        } for r in holyrood_records]
        # Synthetic Holyrood records for the pre-review polygons. They don't
        # appear in holyrood_winners.json (18 only joins to current SPC26),
        # but DOM elements need to exist for paintAtYear to light them up at
        # year < 2026. Initial fill = grey; winner/year come from
        # HOLYROOD_HISTORY at slider time.
        pre_meta_by_key = holyrood_history.get('spcs', {})
        for key, meta in all_spcs_pre.items():
            holyrood_js.append({
                'spc': key,
                'n':   meta.get('name', '') or pre_meta_by_key.get(key, {}).get('name', ''),
                'w':   None,
                'y':   None,
            })
        n_h_winner = sum(1 for h in holyrood_js if h['w'])
        print(f'holyrood spcs in gb: {len(holyrood_js)} (with winner: {n_h_winner}; '
              f'grey: {len(holyrood_js) - n_h_winner}; '
              f'incl. {len(all_spcs_pre)} pre-review polygons hidden at year >= 2026)')

    # Senedd 2026 overlay (GB only) — one record + path per constituency,
    # painted by plurality party with the 6-seat split in the tooltip.
    #
    # Phase 1D (#72) adds the pre-review polygon set (NAWC21, used at the
    # 2016 + 2021 elections) under senedd_geoms_2007 plus per-constituency
    # history under senedd_history. Era classification mirrors Holyrood:
    #   'pre'  → visible at year <  2026 (PRE_<NAWC21CD>; 2007 boundary set)
    #   'post' → visible at year >= 2026 (bare S01..S16; 2026 layout)
    senedd_paths: dict = {
        code: c['path'] for code, c in senedd_geoms.get('constituencies', {}).items()
    }
    senedd_paths_pre: dict = {}
    senedd_eras: dict = {}
    senedd_js = [{
        's':     r['code'],
        'n':     r['name'],
        'w':     r['plurality_party'],
        'y':     r['year'],
        'seats': r['seats'],
        'votes': r['votes'],
    } for r in senedd_records]
    if region == 'gb':
        all_senedd_pre = senedd_geoms_2007.get('constituencies', {})
        senedd_paths_pre = {f'PRE_{code}': c['path']
                            for code, c in all_senedd_pre.items()}
        for code in senedd_paths:
            senedd_eras[code] = 'post'
        for key in senedd_paths_pre:
            senedd_eras[key] = 'pre'
        # Synthetic Senedd records for the pre-review polygons. They don't
        # appear in senedd_2026.json (15 only joins to the 2026 16-seat
        # layout), but DOM elements need to exist for paintAtYear to light
        # them up at year < 2026. Initial fill = grey; winner/year come
        # from SENEDD_HISTORY at slider time.
        pre_meta_by_key = senedd_history.get('constituencies', {})
        for code in all_senedd_pre:
            key = f'PRE_{code}'
            meta = pre_meta_by_key.get(key, {})
            senedd_js.append({
                's':     key,
                'n':     meta.get('name', all_senedd_pre[code].get('name', '')),
                'w':     None,
                'y':     None,
                'seats': {},
                'votes': {},
            })
        n_senedd_winner = sum(1 for s in senedd_js if s['w'])
        print(f'senedd in gb: {len(senedd_js)} (with winner: {n_senedd_winner}; '
              f'grey: {len(senedd_js) - n_senedd_winner}; '
              f'incl. {len(senedd_paths_pre)} pre-review polygons hidden at year >= 2026)')

    # GE 2024 overlay (GB only) — one record + path per Westminster
    # constituency, painted by 2024 GE winner with the candidate name in the
    # tooltip. Pre-filtered to GB above.
    #
    # Phase 1E (#71) adds the pre-review polygon set (PCON_DEC_2021, same
    # geometry as PCON_DEC_2010 — Westminster boundaries did not change
    # between 2010 and the July 2024 review) under `pcon_geoms_2010` plus
    # per-PCON × per-year history under `ge_history` (HoC Library CBP-8647).
    # Era classification mirrors Holyrood / Senedd:
    #   'pre'  → visible at year <  2024 (PRE_<PCON21CD>; 2010 boundary set,
    #             driven by ge_history at slider time)
    #   'post' → visible at year >= 2024 (bare PCON24CD; July 2024 review,
    #             single-year fill from ge2024.json)
    pcon_paths: dict = {
        code: c['path']
        for code, c in pcon_geoms.get('constituencies', {}).items()
        if code.startswith(GB_PCON_PREFIXES)
    }
    pcon_paths_pre: dict = {}
    pcon_eras: dict = {}
    pcon_js = [{
        'p': r['code'],
        'n': r['name'],
        'w': r['winner_party'],
        'c': r['candidate'],
        'y': r['year'],
    } for r in pcon_records]
    if region == 'gb':
        # Era stamping — 2024 polygons are 'post', 2010 polygons are 'pre'.
        # Keys for the 2010 set use a PRE_<PCON21CD> prefix to keep them
        # disjoint from the 5 Scottish PCON24CDs that overlap (boundaries
        # unchanged for those 5 seats, but the era distinction still matters
        # because the historical record lives in ge_history, not ge2024).
        for code in pcon_paths:
            pcon_eras[code] = 'post'
        all_pcon_pre = pcon_geoms_2010.get('constituencies', {})
        # Mirror the GB filter applied to the 2024 set — N06* (NI) gets
        # excluded at render time. Code prefixes in the 2010 set are
        # E14/W07/S14/N06 (note N06 vs. 2024's N05 because the 2010 codes
        # are a separate registry).
        pcon_paths_pre = {
            f'PRE_{code}': c['path']
            for code, c in all_pcon_pre.items()
            if code.startswith(GB_PCON_PREFIXES)
        }
        for key in pcon_paths_pre:
            pcon_eras[key] = 'pre'
        # Synthetic PCON records for the pre-review polygons. They don't
        # appear in ge2024.json (which is 2024-only), but DOM elements need
        # to exist for paintAtYear to light them up at year < 2024. Initial
        # fill = grey; winner / year / candidate come from PCON_HISTORY at
        # slider time.
        pre_meta_by_key = ge_history.get('pcons', {})
        for code in all_pcon_pre:
            if not code.startswith(GB_PCON_PREFIXES):
                continue
            key = f'PRE_{code}'
            meta = pre_meta_by_key.get(code, {})
            pcon_js.append({
                'p': key,
                'n': meta.get('name', all_pcon_pre[code].get('name', '')),
                'w': None,
                'c': None,
                'y': None,
            })
        n_pcon_winner = sum(1 for p in pcon_js if p['w'])
        print(f'pcon in gb: {len(pcon_js):,} (with winner: {n_pcon_winner:,}; '
              f'grey: {len(pcon_js) - n_pcon_winner:,}; '
              f'incl. {len(pcon_paths_pre):,} pre-review polygons hidden at year >= 2024)')

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

        # Ward-history coverage report — issue #70 acceptance gauge.
        n_history_wards = len(ward_history.get('wards', {}))
        n_ward_years = sum(len(w.get('history', []))
                            for w in ward_history.get('wards', {}).values())
        print(f'ward history: {n_history_wards:,} wards across '
              f'{len(ward_history.get("years", []))} year stops, '
              f'{n_ward_years:,} ward-years')

        # CED-history coverage report (issue #69 phase 1B / #73).
        n_history_ceds = len(ced_history.get('ceds', {}))
        n_ced_years = sum(len(c.get('history', []))
                            for c in ced_history.get('ceds', {}).values())
        print(f'ced history: {n_history_ceds:,} CED polygons across '
              f'{len(ced_history.get("years", []))} year stops, '
              f'{n_ced_years:,} CED-years')

        # Holyrood-history coverage report (issue #69 phase 1C / #74).
        n_history_spcs = len(holyrood_history.get('spcs', {}))
        n_spc_years = sum(len(s.get('history', []))
                            for s in holyrood_history.get('spcs', {}).values())
        print(f'holyrood history: {n_history_spcs} SPC polygons across '
              f'{len(holyrood_history.get("years", []))} year stops, '
              f'{n_spc_years:,} SPC-years')

        # Senedd-history coverage report (issue #69 phase 1D / #72).
        n_history_senedd = len(senedd_history.get('constituencies', {}))
        n_senedd_years = sum(len(c.get('history', []))
                              for c in senedd_history.get('constituencies', {}).values())
        n_history_regions = len(senedd_history.get('regions', {}))
        n_region_years = sum(len(r.get('history', []))
                              for r in senedd_history.get('regions', {}).values())
        print(f'senedd history: {n_history_senedd} constituency polygons + '
              f'{n_history_regions} regions across '
              f'{len(senedd_history.get("years", []))} year stops '
              f'({n_senedd_years} constituency-years, {n_region_years} region-years)')

        # GE-history coverage report (issue #69 phase 1E / #71). Only GB
        # rows are reported — N06* records sit in ge_history.json but are
        # filtered out at render time, mirroring the 2024-side N05 filter.
        gb_history_pcons = [c for c in ge_history.get('pcons', {})
                            if c.startswith(GB_PCON_PREFIXES)]
        n_pcon_history_years = sum(
            len(p.get('history', []))
            for c, p in ge_history.get('pcons', {}).items()
            if c.startswith(GB_PCON_PREFIXES)
        )
        # Year stops = HoC's 4 (2010/2015/2017/2019) plus the GE 2024
        # contest carried in ge2024.json (PCON_HISTORY holds a one-entry
        # history per post-era key). The two registries stay separate so
        # 19b/20b regenerates without re-running the GE 2024 pipeline.
        slider_pcon_years = sorted(set(ge_history.get('years', [])) | {2024})
        print(f'ge history: {len(gb_history_pcons)} pre-era + {len(pcon_paths)} '
              f'post-era PCON polygons across {len(slider_pcon_years)} year stops '
              f'({n_pcon_history_years:,} PCON-years from HoC + '
              f'{len(pcon_paths)} from ge2024.json)')

    js = []
    js.append('const VIEWBOX = ' + json.dumps(geoms['viewBoxes'][region]) + ';')
    js.append('const WARD_PATHS = ' + json.dumps(ward_paths, separators=(',', ':')) + ';')
    js.append('const BOROUGH_PATHS = ' + json.dumps(borough_paths, separators=(',', ':')) + ';')
    js.append('const COUNTRY_PATHS = ' + json.dumps(country_paths, separators=(',', ':')) + ';')
    js.append('const CED_PATHS = ' + json.dumps(ced_paths, separators=(',', ':')) + ';')
    js.append('const CED_PATHS_PRE = ' + json.dumps(ced_paths_pre, separators=(',', ':')) + ';')
    js.append('const CED_ERAS = ' + json.dumps(ced_eras, separators=(',', ':')) + ';')
    js.append('const HOLYROOD_PATHS = ' + json.dumps(holyrood_paths, separators=(',', ':')) + ';')
    js.append('const HOLYROOD_PATHS_PRE = ' + json.dumps(holyrood_paths_pre, separators=(',', ':')) + ';')
    js.append('const HOLYROOD_ERAS = ' + json.dumps(holyrood_eras, separators=(',', ':')) + ';')
    js.append('const SENEDD_PATHS = ' + json.dumps(senedd_paths, separators=(',', ':')) + ';')
    js.append('const SENEDD_PATHS_PRE = ' + json.dumps(senedd_paths_pre, separators=(',', ':')) + ';')
    js.append('const SENEDD_ERAS = ' + json.dumps(senedd_eras, separators=(',', ':')) + ';')
    js.append('const PCON_PATHS = ' + json.dumps(pcon_paths, separators=(',', ':')) + ';')
    js.append('const PCON_PATHS_PRE = ' + json.dumps(pcon_paths_pre, separators=(',', ':')) + ';')
    js.append('const PCON_ERAS = ' + json.dumps(pcon_eras, separators=(',', ':')) + ';')
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

function makePath(d, cls, fill, titleText, ds) {
  const p = document.createElementNS(SVG_NS, 'path');
  p.setAttribute('d', d);
  p.setAttribute('class', cls);
  if (fill) p.setAttribute('fill', fill);
  if (titleText) {
    const t = document.createElementNS(SVG_NS, 'title');
    t.textContent = titleText;
    p.appendChild(t);
  }
  if (ds) {
    for (const k of Object.keys(ds)) {
      if (ds[k] != null) p.dataset[k] = ds[k];
    }
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
    ...CEDS.map(c => ({  kind: 'ced',
                         d: CED_PATHS[c.ced] || CED_PATHS_PRE[c.ced], y: c.y,
                         fill: (c.w && PARTY_COLOURS[c.w]) || NEUTRAL_FILL,
                         title: fmtCedTitle(c),
                         ds: { ced: c.ced, era: CED_ERAS[c.ced] || 'any' } })),
    ...HOLYROOD.map(h => ({ kind: 'holyrood',
                            d: HOLYROOD_PATHS[h.spc] || HOLYROOD_PATHS_PRE[h.spc],
                            y: h.y,
                            fill: (h.w && PARTY_COLOURS[h.w]) || NEUTRAL_FILL,
                            title: fmtHolyroodTitle(h),
                            ds: { spc: h.spc, era: HOLYROOD_ERAS[h.spc] || 'post' } })),
    ...SENEDD.map(s => ({ kind: 'senedd',
                          d: SENEDD_PATHS[s.s] || SENEDD_PATHS_PRE[s.s], y: s.y,
                          fill: (s.w && PARTY_COLOURS[s.w]) || NEUTRAL_FILL,
                          title: fmtSeneddTitle(s),
                          ds: { senedd: s.s, era: SENEDD_ERAS[s.s] || 'post' } })),
    ...PCON.map(p => ({ kind: 'pcon',
                        d: PCON_PATHS[p.p] || PCON_PATHS_PRE[p.p], y: p.y,
                        fill: (p.w && PARTY_COLOURS[p.w]) || NEUTRAL_FILL,
                        title: fmtPconTitle(p),
                        ds: { pcon: p.p, era: PCON_ERAS[p.p] || 'post' } })),
    ...SURREY.map(s => ({ kind: 'surrey', d: SURREY_PATHS[s.c], y: s.y,
                          fill: (s.w && PARTY_COLOURS[s.w]) || NEUTRAL_FILL,
                          title: fmtSurreyTitle(s) })),
  ].filter(it => it.d);
  items.sort((a, b) => (a.y ?? 0) - (b.y ?? 0) || (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]));
  const fills = document.createElementNS(SVG_NS, 'g');
  fills.setAttribute('class', 'fills');
  items.forEach(it => fills.appendChild(
    makePath(it.d, it.kind, it.fill, it.title, it.ds)
  ));
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

    # === Time slider (issue #70 phase 1A) — GB only ===
    # Two extra constants + a second render block, gated on --region=gb so
    # GM output stays byte-identical. The slider chrome lives in the
    # hand-authored HTML below the legend; this JS finds it and wires it up.
    if region == 'gb' and ward_history.get('years'):
        # Union the year stops across every history source so the slider
        # exposes a tick for every contest year that drives a repaint —
        # 2016 is Holyrood-only (no ward contests), but the slider still
        # needs that tick to land readers there. Sorted ascending.
        # Phase 1E (#71) adds 2015 (and 2017 / 2019 if they weren't already
        # in the union — they are, via ward / CED contests).
        slider_years = sorted(set(ward_history.get('years', []))
                              | set(ced_history.get('years', []))
                              | set(holyrood_history.get('years', []))
                              | set(senedd_history.get('years', []))
                              | set(ge_history.get('years', [])))
        js.append('')
        js.append('const YEARS = ' + json.dumps(slider_years) + ';')
        js.append('const WARD_HISTORY = ' + json.dumps(
            ward_history['wards'], separators=(',', ':')) + ';')
        js.append('const CED_HISTORY = ' + json.dumps(
            ced_history.get('ceds', {}), separators=(',', ':')) + ';')
        js.append('const HOLYROOD_HISTORY = ' + json.dumps(
            holyrood_history.get('spcs', {}), separators=(',', ':'),
            ensure_ascii=False) + ';')
        # SENEDD_HISTORY shape:
        #   {<polygon_key>: {name, region, history: [{y, w, src, url, candidate?}]}}
        # SENEDD_REGION_HISTORY (issue #69 phase 1D / #72 commit 6) carries
        # the d'Hondt regional-list seat allocations per region per year for
        # the 2016+2021 elections. Each entry has both `seats` (normalised
        # labels for downstream sorting) and `seats_raw` (raw Wikipedia
        # party strings — e.g. "UK Independence Party" — so the tooltip
        # can render historical accuracy where normalize_party would flatten
        # to "Other"). SENEDD_RAW_DISPLAY shortens the raw labels for the
        # tooltip without losing the distinction.
        js.append('const SENEDD_HISTORY = ' + json.dumps(
            senedd_history.get('constituencies', {}), separators=(',', ':'),
            ensure_ascii=False) + ';')
        js.append('const SENEDD_REGION_HISTORY = ' + json.dumps(
            senedd_history.get('regions', {}), separators=(',', ':'),
            ensure_ascii=False) + ';')
        js.append('const SENEDD_RAW_DISPLAY = ' + json.dumps({
            'Welsh Labour':              'Lab',
            'Welsh Conservatives':       'Con',
            'Plaid Cymru':               'Plaid',
            'Welsh Liberal Democrats':   'LibDem',
            'UK Independence Party':     'UKIP',
            'Green Party of England and Wales': 'Green',
            'Reform UK':                 'Reform',
            'Abolish the Welsh Assembly Party': 'Abolish',
            'Independent':               'Indep',
            'Independent (politician)':  'Indep',
        }) + ';')

        # PCON_HISTORY (issue #69 phase 1E / #71). Keyed by polygon key —
        # PRE_<PCON21CD> for pre-era 2010-boundary polygons (3 history
        # entries: 2015 / 2017 / 2019, from HoC Library CBP-8647), bare
        # PCON24CD for post-era 2024-boundary polygons (1 history entry:
        # 2024, from ge2024.json). paintAtYear at year < 2024 walks PRE_*
        # histories; at year >= 2024 walks bare-code histories.
        pcon_history: dict = {}
        for code, p in ge_history.get('pcons', {}).items():
            if not code.startswith(GB_PCON_PREFIXES):
                continue
            pcon_history[f'PRE_{code}'] = {
                'name': p.get('name', ''),
                'history': p.get('history', []),
            }
        # Seed post-era 2024 records from ge2024.json so the same dict
        # carries both eras. The renderer's lookup is PCON_HISTORY[el.dataset.pcon]
        # — eras are disjoint by polygon-key construction (PRE_ prefix vs bare),
        # so there's no collision.
        for r in pcon_records:
            pcon_history[r['code']] = {
                'name': r['name'],
                'history': [{
                    'y': r['year'],
                    'w': r['winner_party'],
                    'candidate': r.get('candidate'),
                    'src': 'wiki',
                    # ge2024.json doesn't carry a per-PCON URL — the
                    # tooltip will show "winner: X (Candidate)" without
                    # a Source line, matching today's behaviour. Leave
                    # empty so the click handler's `!dataset.url` guard
                    # keeps the cursor at default for 2024-era seats.
                    'url': '',
                }],
            }
        js.append('const PCON_HISTORY = ' + json.dumps(
            pcon_history, separators=(',', ':'), ensure_ascii=False) + ';')
        js.append(r'''
// Stamp each ward <path> with data-gss / data-year so paintAtYear can
// look it up. Done here (GB-only splice) rather than in the shared
// renderer so docs/current.html (GM) stays byte-identical. Path `d`
// strings are unique per ward, so a {d -> {gss, y}} map keyed on the
// ward's own WARD_PATHS entry is a safe join.
(function attachWardMeta() {
  const wardByPath = new Map(
    WARDS.map(w => [WARD_PATHS[w.gss], { gss: w.gss, y: w.y }])
  );
  document.querySelectorAll('.map-svg path.ward').forEach(el => {
    const meta = wardByPath.get(el.getAttribute('d'));
    if (!meta) return;
    if (meta.gss) el.dataset.gss = meta.gss;
    if (meta.y != null) el.dataset.year = String(meta.y);
  });
})();

// Attach initial source URLs to each ward <path>. data-gss and data-year
// were stamped above; look up the matching history entry by gss + year
// and store its url.
(function attachWardURLs() {
  document.querySelectorAll('.map-svg path.ward[data-gss]').forEach(el => {
    const wh = WARD_HISTORY[el.dataset.gss];
    if (!wh) return;
    const dsYear = Number(el.dataset.year);
    if (!dsYear) return;
    const cur = wh.history.find(e => e.y === dsYear);
    if (cur && cur.url) el.dataset.url = cur.url;
  });
})();

// paintAtYear — rewrite ward + CED fills (and dataset metadata) for the
// given year. rAF-coalesced: the latest requested year is stored
// synchronously in _pendingYear and consumed inside the rAF, so fast
// slider drags don't drop intermediate values. lastPaintedYear short-
// circuits true no-ops.
//
// For CEDs, era visibility kicks in alongside carry-forward fill:
//   data-era="pre"  → hidden at year >= 2026 (Norfolk/Essex/Suffolk
//                     2017+2021 boundaries; Surrey CC pre-abolition).
//   data-era="post" → hidden at year <  2026 (Norfolk/Essex/Suffolk
//                     LGBCE post-review).
//   data-era="any"  → always visible (17 counties unchanged 2017–2025).
let _lastPaintedYear = null;
let _pendingYear = null;
let _rafPending = false;
function paintAtYear(targetYear) {
  _pendingYear = targetYear;
  if (targetYear === _lastPaintedYear && !_rafPending) return;
  if (_rafPending) return;
  _rafPending = true;
  requestAnimationFrame(() => {
    _rafPending = false;
    const y = _pendingYear;
    _lastPaintedYear = y;
    const root = document.querySelector('.map-svg');
    if (!root) return;
    // Each overlay layer paints from its actual contest year onwards.
    // .slider-pre-2025 is dead code today (CEDs moved to inline-style era
    // control in #73 phase 1B); .slider-pre-2026 still gates Surrey via
    // CSS. CEDs (#73 phase 1B), Holyrood (#74 phase 1C), Senedd (#72
    // phase 1D), and PCON (#71 phase 1E) now use inline-style era control
    // below so pre-review polygons can light up at year < their era boundary.
    root.classList.toggle('slider-pre-2025', y < 2025);
    root.classList.toggle('slider-pre-2026', y < 2026);
    root.querySelectorAll('path.ward').forEach(el => {
      const gss = el.dataset.gss;
      const wh = gss && WARD_HISTORY[gss];
      if (!wh) {
        el.setAttribute('fill', NEUTRAL_FILL);
        delete el.dataset.year;
        delete el.dataset.url;
        return;
      }
      // history is sorted ascending; find the most recent entry with y<=targetYear.
      let chosen = null;
      for (const entry of wh.history) {
        if (entry.y <= y) chosen = entry;
        else break;
      }
      if (chosen) {
        el.setAttribute('fill', PARTY_COLOURS[chosen.w] || NEUTRAL_FILL);
        el.dataset.year = String(chosen.y);
        // Only set data-url when we actually have a source — an empty
        // attribute still matches the `path.ward[data-url]` pointer-cursor
        // rule in shared.css and would advertise a non-functional click.
        if (chosen.url) el.dataset.url = chosen.url;
        else delete el.dataset.url;
      } else {
        el.setAttribute('fill', NEUTRAL_FILL);
        delete el.dataset.year;
        delete el.dataset.url;
      }
    });
    root.querySelectorAll('path.ced').forEach(el => {
      const era = el.dataset.era || 'any';
      const visible = era === 'pre'  ? (y <  2026)
                    : era === 'post' ? (y >= 2026)
                    : true;
      el.style.display = visible ? '' : 'none';
      if (!visible) return;
      const key = el.dataset.ced;
      const ch = key && CED_HISTORY[key];
      if (!ch) {
        el.setAttribute('fill', NEUTRAL_FILL);
        delete el.dataset.year;
        delete el.dataset.url;
        return;
      }
      let chosen = null;
      for (const entry of ch.history) {
        if (entry.y <= y) chosen = entry;
        else break;
      }
      if (chosen) {
        el.setAttribute('fill', PARTY_COLOURS[chosen.w] || NEUTRAL_FILL);
        el.dataset.year = String(chosen.y);
        if (chosen.url) el.dataset.url = chosen.url;
        else delete el.dataset.url;
        const titleEl = el.querySelector('title');
        if (titleEl) {
          const tl = [(ch.county || '') + ' County Council · ' + (ch.division || '')];
          tl.push(chosen.y + ' · winner: ' + (PARTY_DISPLAY[chosen.w] || chosen.w));
          if (chosen.url) {
            try { tl.push('Source: ' + new URL(chosen.url).hostname + ' — click to open'); }
            catch (_) { /* invalid URL */ }
          }
          titleEl.textContent = tl.join('\n');
        }
      } else {
        el.setAttribute('fill', NEUTRAL_FILL);
        delete el.dataset.year;
        delete el.dataset.url;
      }
    });
    // Holyrood layer — same era + carry-forward shape as CEDs (#74 phase 1C):
    //   data-era="pre"  → hidden at year >= 2026 (PRE_<SPC22CD>; 2014 boundaries)
    //   data-era="post" → hidden at year <  2026 (bare S16000***; 2026 review)
    root.querySelectorAll('path.holyrood').forEach(el => {
      const era = el.dataset.era || 'post';
      const visible = era === 'pre' ? (y < 2026) : (y >= 2026);
      el.style.display = visible ? '' : 'none';
      if (!visible) return;
      const key = el.dataset.spc;
      const sh = key && HOLYROOD_HISTORY[key];
      if (!sh) {
        el.setAttribute('fill', NEUTRAL_FILL);
        delete el.dataset.year;
        delete el.dataset.url;
        return;
      }
      let chosen = null;
      for (const entry of sh.history) {
        if (entry.y <= y) chosen = entry;
        else break;
      }
      if (chosen) {
        el.setAttribute('fill', PARTY_COLOURS[chosen.w] || NEUTRAL_FILL);
        el.dataset.year = String(chosen.y);
        if (chosen.url) el.dataset.url = chosen.url;
        else delete el.dataset.url;
        const titleEl = el.querySelector('title');
        if (titleEl) {
          const tl = ['Scottish Parliament · ' + (sh.name || '')];
          const winLine = chosen.y + ' · winner: ' + (PARTY_DISPLAY[chosen.w] || chosen.w);
          tl.push(chosen.candidate ? winLine + ' (' + chosen.candidate + ')' : winLine);
          if (chosen.url) {
            try { tl.push('Source: ' + new URL(chosen.url).hostname + ' — click to open'); }
            catch (_) { /* invalid URL */ }
          }
          titleEl.textContent = tl.join('\n');
        }
      } else {
        el.setAttribute('fill', NEUTRAL_FILL);
        delete el.dataset.year;
        delete el.dataset.url;
      }
    });
    // Senedd layer — same era + carry-forward shape as Holyrood (#72 phase 1D):
    //   data-era="pre"  → hidden at year >= 2026 (PRE_<NAWC21CD>; 2007 40-seat layout)
    //   data-era="post" → hidden at year <  2026 (bare S01..S16; 2026 16-seat layout)
    // SENEDD_HISTORY is keyed by polygon key (`PRE_<NAWC21CD>` for pre-review,
    // bare `S0x` for current era).
    //
    // Tooltip behaviour: era=pre rebuilds the tooltip from SENEDD_HISTORY
    // (FPTP winner + region label + source URL); era=post leaves the initial
    // fmtSeneddTitle tooltip in place because it already carries the rich
    // 6-seat split that the historical PR layout doesn't have. Only fill /
    // dataset metadata are refreshed for era=post — the rewrite would
    // otherwise lose the seats line on every slider tick.
    root.querySelectorAll('path.senedd').forEach(el => {
      const era = el.dataset.era || 'post';
      const visible = era === 'pre' ? (y < 2026) : (y >= 2026);
      el.style.display = visible ? '' : 'none';
      if (!visible) return;
      const key = el.dataset.senedd;
      const sh = key && SENEDD_HISTORY[key];
      if (!sh) {
        el.setAttribute('fill', NEUTRAL_FILL);
        delete el.dataset.year;
        delete el.dataset.url;
        return;
      }
      let chosen = null;
      for (const entry of sh.history) {
        if (entry.y <= y) chosen = entry;
        else break;
      }
      if (chosen) {
        el.setAttribute('fill', PARTY_COLOURS[chosen.w] || NEUTRAL_FILL);
        el.dataset.year = String(chosen.y);
        if (chosen.url) el.dataset.url = chosen.url;
        else delete el.dataset.url;
        if (era === 'pre') {
          const titleEl = el.querySelector('title');
          if (titleEl) {
            const tl = ['Senedd · ' + (sh.name || '')];
            if (sh.region) tl.push('Region: ' + sh.region);
            const winLine = chosen.y + ' · winner: ' + (PARTY_DISPLAY[chosen.w] || chosen.w);
            tl.push(chosen.candidate ? winLine + ' (' + chosen.candidate + ')' : winLine);
            // Regional list breakdown (issue #69 phase 1D / #72 commit 6).
            // For each pre-review constituency at year < 2026, splice in
            // the four list-seat winners for the constituency's electoral
            // region, carry-forwarded the same way as the constituency
            // winner. Prefer the raw seat dict over the normalised one so
            // historically distinct labels like UKIP, Welsh Labour, etc.
            // render as themselves rather than collapsing to "Other".
            const rh = sh.region && SENEDD_REGION_HISTORY[sh.region];
            if (rh && rh.history) {
              let regionChosen = null;
              for (const e of rh.history) {
                if (e.y <= y) regionChosen = e;
                else break;
              }
              if (regionChosen) {
                const raw = regionChosen.seats_raw || {};
                const useRaw = Object.keys(raw).length > 0;
                const seats = useRaw ? raw : (regionChosen.seats || {});
                const entries = Object.entries(seats).sort((a, b) => b[1] - a[1]);
                if (entries.length) {
                  const label = entries.map(([p, n]) => {
                    const display = useRaw
                      ? (SENEDD_RAW_DISPLAY[p] || p)
                      : (PARTY_DISPLAY[p] || p);
                    return display + ' ' + n;
                  }).join(', ');
                  tl.push('Regional list ' + regionChosen.y + ': ' + label);
                }
              }
            }
            if (chosen.url) {
              try { tl.push('Source: ' + new URL(chosen.url).hostname + ' — click to open'); }
              catch (_) { /* invalid URL */ }
            }
            titleEl.textContent = tl.join('\n');
          }
        }
      } else {
        el.setAttribute('fill', NEUTRAL_FILL);
        delete el.dataset.year;
        delete el.dataset.url;
      }
    });
    // PCON (Westminster) layer — era + carry-forward shape (#71 phase 1E):
    //   data-era="pre"  → hidden at year >= 2024 (PRE_<PCON21CD>; 2010 boundaries
    //                     in legal effect at 2015 / 2017 / 2019)
    //   data-era="post" → hidden at year <  2024 (bare PCON24CD; July 2024 review)
    // PCON_HISTORY is keyed by polygon key (PRE_<code> for pre-era, bare code
    // for post-era). Pre-era entries carry a HoC briefing URL for click-through;
    // post-era entries have an empty URL string (ge2024.json doesn't carry one).
    root.querySelectorAll('path.pcon').forEach(el => {
      const era = el.dataset.era || 'post';
      const visible = era === 'pre' ? (y < 2024) : (y >= 2024);
      el.style.display = visible ? '' : 'none';
      if (!visible) return;
      const key = el.dataset.pcon;
      const ph = key && PCON_HISTORY[key];
      if (!ph) {
        el.setAttribute('fill', NEUTRAL_FILL);
        delete el.dataset.year;
        delete el.dataset.url;
        return;
      }
      let chosen = null;
      for (const entry of ph.history) {
        if (entry.y <= y) chosen = entry;
        else break;
      }
      if (chosen) {
        el.setAttribute('fill', PARTY_COLOURS[chosen.w] || NEUTRAL_FILL);
        el.dataset.year = String(chosen.y);
        if (chosen.url) el.dataset.url = chosen.url;
        else delete el.dataset.url;
        const titleEl = el.querySelector('title');
        if (titleEl) {
          const tl = ['Westminster · ' + (ph.name || '')];
          const winLine = chosen.y + ' · winner: ' + (PARTY_DISPLAY[chosen.w] || chosen.w);
          tl.push(chosen.candidate ? winLine + ' (' + chosen.candidate + ')' : winLine);
          if (chosen.url) {
            try { tl.push('Source: ' + new URL(chosen.url).hostname + ' — click to open'); }
            catch (_) { /* invalid URL */ }
          }
          titleEl.textContent = tl.join('\n');
        }
      } else {
        el.setAttribute('fill', NEUTRAL_FILL);
        delete el.dataset.year;
        delete el.dataset.url;
      }
    });
  });
}

// Click any ward / CED / Holyrood / Senedd / PCON polygon to open its
// source URL — lets readers verify accuracy and report errors against
// the canonical source. PCON click-through covers pre-era HoC Library
// data (2015 / 2017 / 2019); post-era PCON (2024) has no URL in
// ge2024.json and so does nothing on click, same as today.
(function wireClicks() {
  const root = document.querySelector('.map-svg');
  if (!root) return;
  root.addEventListener('click', evt => {
    const target = evt.target.closest(
      'path.ward, path.ced, path.holyrood, path.senedd, path.pcon');
    if (!target || !target.dataset.url) return;
    window.open(target.dataset.url, '_blank', 'noopener,noreferrer');
  });
})();

// Refresh the SVG <title> tooltip on hover so the year + source URL
// reflect the slider's current position rather than the at-render snapshot.
// The "viewing year" is the slider's last-requested year (_pendingYear);
// the per-ward dataset.year is the year the ward was last *contested* and
// can lag the slider when no entry exists at the current position.
// The renderer's fmtTitle appends a "County Council · …" subtitle for
// 2-tier wards; the slider data has no county info to splice in, so
// preserve any such trailing line(s) verbatim across the rewrite.
(function wireTooltips() {
  const root = document.querySelector('.map-svg');
  if (!root) return;
  root.addEventListener('mouseover', evt => {
    const target = evt.target.closest('path.ward');
    if (!target) return;
    const gss = target.dataset.gss;
    if (!gss) return;
    const wh = WARD_HISTORY[gss];
    if (!wh) return;
    const viewingYear = (_pendingYear != null) ? _pendingYear
      : (Number(target.dataset.year) || YEARS[YEARS.length - 1]);
    const dsYear = Number(target.dataset.year);
    const entry = dsYear ? wh.history.find(e => e.y === dsYear) : null;
    const titleEl = target.querySelector('title');
    if (!titleEl) return;
    // Snapshot any "County Council · …" tail line from the existing title
    // so the 2-tier subtitle survives the rewrite. Snapshot once per <title>
    // (the first hover may have already overwritten the textContent on a
    // re-hovered element — use a data-attribute as the canonical store).
    if (!('countySuffix' in target.dataset)) {
      const existing = titleEl.textContent || '';
      const ccLines = existing.split('\n').filter(l =>
        l.startsWith('County Council · '));
      target.dataset.countySuffix = ccLines.join('\n');
    }
    const lines = [wh.borough + ' · ' + wh.ward];
    if (entry) {
      lines.push('Last election: ' + entry.y + ' · winner: ' + (PARTY_DISPLAY[entry.w] || entry.w));
      if (entry.url) {
        try {
          lines.push('Source: ' + new URL(entry.url).hostname + ' — click to open');
        } catch (_) { /* invalid URL */ }
      }
    } else {
      lines.push('(no result for ' + viewingYear + ')');
    }
    if (target.dataset.countySuffix) {
      lines.push(target.dataset.countySuffix);
    }
    titleEl.textContent = lines.join('\n');
  });
})();

// Wire the slider chrome below the legend. If the chrome isn't present
// (e.g. mid-deploy with stale HTML), the slider silently does nothing.
(function wireSlider() {
  const sliderRoot = document.querySelector('.time-slider');
  if (!sliderRoot) return;
  const range = sliderRoot.querySelector('.time-slider-range');
  const playBtn = sliderRoot.querySelector('.time-slider-play');
  const speedBtn = sliderRoot.querySelector('.time-slider-speed');
  const yearLabel = sliderRoot.querySelector('.time-slider-year');
  const ticks = sliderRoot.querySelector('.time-slider-ticks');
  if (!range || !playBtn || !speedBtn || !yearLabel) return;

  range.min = '0';
  range.max = String(YEARS.length - 1);
  range.step = '1';
  range.value = String(YEARS.length - 1);
  if (ticks) {
    ticks.innerHTML = '';
    YEARS.forEach(y => {
      const span = document.createElement('span');
      span.textContent = String(y);
      ticks.appendChild(span);
    });
  }
  yearLabel.textContent = String(YEARS[YEARS.length - 1]);

  function applyIndex(idx) {
    idx = Math.max(0, Math.min(YEARS.length - 1, idx));
    range.value = String(idx);
    const y = YEARS[idx];
    yearLabel.textContent = String(y);
    paintAtYear(y);
  }

  const SPEEDS_MS = [1000, 500, 250];
  let speedIdx = 0;
  let timerId = null;
  let playing = false;

  function setSpeed(i) {
    speedIdx = i % SPEEDS_MS.length;
    speedBtn.textContent = (1 << speedIdx) + '×';
    if (playing) {
      clearInterval(timerId);
      timerId = setInterval(step, SPEEDS_MS[speedIdx]);
    }
  }

  function step() {
    const cur = parseInt(range.value, 10);
    if (cur >= YEARS.length - 1) { stop(); return; }
    applyIndex(cur + 1);
  }

  function play() {
    if (playing) return;
    const cur = parseInt(range.value, 10);
    if (cur >= YEARS.length - 1) applyIndex(0);
    playing = true;
    playBtn.textContent = 'Pause';
    playBtn.setAttribute('aria-pressed', 'true');
    timerId = setInterval(step, SPEEDS_MS[speedIdx]);
  }

  function stop() {
    if (timerId) { clearInterval(timerId); timerId = null; }
    playing = false;
    playBtn.textContent = 'Play';
    playBtn.setAttribute('aria-pressed', 'false');
  }

  playBtn.addEventListener('click', () => (playing ? stop() : play()));
  speedBtn.addEventListener('click', () => setSpeed(speedIdx + 1));
  range.addEventListener('input', () => {
    if (playing) stop();
    applyIndex(parseInt(range.value, 10));
  });

  setSpeed(0);

  // Initial paint at the rightmost year so era-gated CEDs hide correctly
  // on page load. Without this, pre-review polygons would render visible
  // at year=2026 (the CSS hide rule that previously gated them moved to
  // inline-style in paintAtYear per issue #69 phase 1B / #73).
  applyIndex(YEARS.length - 1);
})();
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
