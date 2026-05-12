"""Build the per-ward "current winner" dataset for the Current map page.

Joins three sources onto the WD24 ward geometry to produce one record per
GB ward (England + Wales + Scotland; NI omitted):

  1. data/all_wards.json            — the 134 councils that contested 2026.
                                       For these, "current" = the 2026 winner
                                       already in `winner`.
  2. data/current_winners_raw.json  — the non-2026 councils, per-ward most-
                                       recent winners scraped by 10+11.
  3. data/ward_geoms.json           — source of truth for the ward identity
                                       (gss code, WD24 name, borough LAD).

Per-council precedence: source 1 (if the LAD appears in all_wards.json with
a non-null winner for this ward) → source 2 (current_winners_raw, by
council name + ward name via the three-tier matcher) → null.

Year is computed per record:
  - all_wards source: 2026 unless the council is all-out + had no 2026
    contest (Salford pattern) — those get `wiki_prior_year` instead.
  - current_winners_raw source: the year stored in the record.

Two-pass name matching (mirrors scripts/07c_build_map_artifact.py):
  pass 1 — normalised (borough, ward) → WD24CD lookup
  pass 2 — walk the override CSV (data/source/ward_name_overrides.csv,
           NEW→OLD scraped-name → gss_name map for boundary-reviewed
           English councils) and retry the normalised lookup.
  Plus optional data/source/current_ward_overrides.csv for Welsh/Scottish
  scrape-side name drift (separate file so concerns stay scoped).

Output: data/current_winners.json — flat list of per-ward records:
  {gss, lad_code, borough, ward, winner, year, source, match_type}
Wards with no source match get winner=null, source="none" (rendered grey
by the Map renderer).
"""
import csv
import json
import re
import sys
from pathlib import Path

from _councils import for_region

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"

# GB-only LAD prefixes. NI wards (N09) are excluded from the Current page —
# Northern Ireland local government runs a separate STV cycle and isn't in
# the scope of this site's GB-focused dataset.
GB_LAD_PREFIXES = ('E06', 'E07', 'E08', 'E09', 'W06', 'S12')


def normalise(s: str) -> str:
    """Loose name match — copy of scripts/07c_build_map_artifact.py:normalise.
    Lowercase, strip dots, slash → space, both apostrophe variants → nothing,
    ' and ' → ' & ', drop trailing '(...)' / ', X' suffixes, collapse spaces."""
    s = s.lower().replace('/', ' ').replace('.', '')
    s = s.replace("’", "").replace("'", "").replace("`", "")
    s = s.replace(' and ', ' & ')
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s)
    s = re.sub(r'\s*,\s+[^,]+$', '', s)
    return ' '.join(s.split())


def normalise_ced(s: str) -> str:
    """Like normalise(), but also strips the divergent CED suffixes:
    ONS uses 'X ED' (Electoral Division), Wikipedia uses 'X Division',
    Wikipedia sometimes uses bare 'X'. Drop any of the three so a single
    canonical key matches across the data sources."""
    s = re.sub(r'\s+(ED|Division)\s*$', '', s, flags=re.IGNORECASE)
    return normalise(s)


def year_for_all_wards_source(council: dict) -> int:
    """Pick the year label for a winner sourced from all_wards.json.

    The 134-council all_wards dataset carries the most-recent winner per
    ward — but the year of that contest depends on the council's cycle:

      - Non-GM contested councils: wiki_2026 set, year = 2026.
      - GM thirds councils: hand-curated CSV, wiki_2026 null, but every
        ward had a 2026 thirds contest — year = 2026.
      - Salford: hand-curated CSV, wiki_2026 null, all-out cycle, only one
        ward (Barton & Winton) had a 2026 by-election; the other 19 wards
        carry their 2021 all-out winners — year = wiki_prior_year (2021).

    Discriminator: an all-out council with no wiki_2026 is the Salford
    pattern; everyone else is 2026.
    """
    if council.get('wiki_2026') is None and council.get('cycle') == 'all-out':
        return council['wiki_prior_year']
    return 2026


def load_geom_overrides() -> dict[tuple[str, str], str]:
    """(lad_code, scraped_name) → gss_name from ward_name_overrides.csv —
    the existing NEW→OLD English boundary-review map (also used by 02/07c)."""
    overrides: dict[tuple[str, str], str] = {}
    with open(SOURCE / 'ward_name_overrides.csv', newline='') as f:
        for row in csv.DictReader(f):
            overrides[(row['lad_code'], row['scraped_name'])] = row['gss_name']
    return overrides


def load_current_overrides() -> dict[tuple[str, str], str]:
    """Optional (council_name, scraped_name) → gss_name overrides scoped to
    the Current scrape (Welsh/Scottish pre-2024 name drift). Missing file
    returns {}."""
    path = SOURCE / 'current_ward_overrides.csv'
    if not path.exists():
        return {}
    overrides: dict[tuple[str, str], str] = {}
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            overrides[(row['council'], row['scraped_name'])] = row['gss_name']
    return overrides


def build_ced_winners(geoms: dict) -> list[dict]:
    """Join CED-level winners (from 6 × 2026 + 14 × 2025 county-council
    Wikipedia articles, parsed by parse_county_article_ceds) onto the
    CED25 polygons in ward_geoms.json. Mirrors the ward-side join shape:
    one record per CED25CD with winner / year / county.

    Source precedence is per-county, not per-record:
      - If the county appears in county_results_2026_ceds.json (i.e. it
        contested in 2026), use ONLY that source. If a specific CED is
        missing or has no extractable winner, the result is null (do NOT
        fall through to 2021 priors — the 2026 contest superseded them
        and showing 2021 data would imply pre-election control).
      - Else if the county appears in current_ced_winners_raw.json (the
        14 × 2025 contested counties), use ONLY that source.
      - Else use county_results_prior_ceds.json (2021 priors — for any
        county whose most recent contest is captured only in the priors).
    """
    p_2026  = DATA / 'county_results_2026_ceds.json'
    p_curr  = DATA / 'current_ced_winners_raw.json'
    p_prior = DATA / 'county_results_prior_ceds.json'
    data_2026  = json.loads(p_2026.read_text())  if p_2026.exists()  else {}
    data_curr  = json.loads(p_curr.read_text())  if p_curr.exists()  else {}
    data_prior = json.loads(p_prior.read_text()) if p_prior.exists() else {}

    def index(ced_map: dict) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for ced_name, rec in ced_map.items():
            key = normalise_ced(ced_name)
            if key in out:
                continue
            out[key] = {
                'party': rec.get('party'),
                'year':  rec.get('year'),
                'source_ced_name': ced_name,
            }
        return out

    by_county_norm: dict[str, dict[str, dict]] = {}
    for county_name in set(data_2026) | set(data_curr) | set(data_prior):
        if county_name in data_2026:
            by_county_norm[county_name] = index(data_2026[county_name])
        elif county_name in data_curr:
            by_county_norm[county_name] = index(data_curr[county_name])
        elif county_name in data_prior:
            by_county_norm[county_name] = index(data_prior[county_name])

    # ONS-side: CED25CD → metadata. Group geoms by parent county for the join.
    out: list[dict] = []
    by_cty_norm_to_county_name: dict[str, str] = {}
    # Map ONS CTY25CD → human county name we use in the data
    for code, meta in geoms.get('ceds', {}).items():
        cty_name = meta.get('cty_name', '') or ''
        # Strip " County" suffix sometimes appended in ONS names.
        cty_clean = re.sub(r'\s+County\s*$', '', cty_name)
        by_cty_norm_to_county_name[meta.get('cty', '')] = cty_clean

    counted = {'matched': 0, 'no_winner': 0}
    for ced_code, meta in geoms.get('ceds', {}).items():
        cty_clean = by_cty_norm_to_county_name.get(meta.get('cty', ''), '')
        ced_county_data = by_county_norm.get(cty_clean, {})
        key = normalise_ced(meta['name'])
        rec = ced_county_data.get(key)
        if rec:
            out.append({
                'ced':     ced_code,
                'cty':     meta.get('cty'),
                'county':  cty_clean,
                'name':    meta['name'],
                'winner':  rec['party'],
                'year':    rec['year'],
            })
            counted['matched'] += 1
        else:
            out.append({
                'ced':     ced_code,
                'cty':     meta.get('cty'),
                'county':  cty_clean,
                'name':    meta['name'],
                'winner':  None,
                'year':    None,
            })
            counted['no_winner'] += 1
    return out, counted


def main():
    with open(DATA / 'all_wards.json') as f:
        all_wards = json.load(f)
    with open(DATA / 'ward_geoms.json') as f:
        geoms = json.load(f)
    raw_path = DATA / 'current_winners_raw.json'
    raw = json.loads(raw_path.read_text()) if raw_path.exists() else {}

    council_by_lad = {c['lad_code']: c for c in for_region('gb')}
    geom_overrides = load_geom_overrides()
    current_overrides = load_current_overrides()

    # Geom-side lookup: (lad_code, normalised(ward_name)) → gss. WD24 names
    # are the source of truth; the loop below iterates the *results* sides
    # and resolves into this map.
    geom_by_norm: dict[tuple[str, str], str] = {}
    geom_meta: dict[str, dict] = {}
    for gss, w in geoms['wards'].items():
        lad = w['lad']
        if not lad.startswith(GB_LAD_PREFIXES):
            continue
        borough = geoms['boroughs'].get(lad, {}).get('name', '')
        geom_by_norm[(lad, normalise(w['name']))] = gss
        geom_meta[gss] = {'lad': lad, 'borough': borough, 'ward': w['name']}

    # Track which gss codes we've already assigned a winner to (a direct
    # match always wins over an override that proxies through the same WD24
    # polygon — mirrors 07c's two-pass behaviour).
    assigned: dict[str, dict] = {}

    def assign(gss: str, winner: str, year, source: str, match_type: str):
        # First write wins; later passes don't overwrite a stronger match.
        if gss in assigned:
            return False
        assigned[gss] = {'winner': winner, 'year': year, 'source': source,
                         'match_type': match_type}
        return True

    # --- Pass 1a: all_wards.json, exact normalised match by (lad, ward) ---
    all_wards_pending: list[dict] = []
    for w in all_wards:
        if not w.get('winner'):
            continue
        lad = w['lad_code']
        if not lad.startswith(GB_LAD_PREFIXES):
            continue
        council = council_by_lad.get(lad)
        if council is None:
            continue
        gss = geom_by_norm.get((lad, normalise(w['ward'])))
        if gss is None:
            all_wards_pending.append(w)
            continue
        assign(gss, w['winner'], year_for_all_wards_source(council),
               '2026', 'exact')

    # --- Pass 1b: all_wards.json, override CSV (NEW→OLD WD24 name) ---
    for w in all_wards_pending:
        override = geom_overrides.get((w['lad_code'], w['ward']))
        if override is None:
            continue
        gss = geom_by_norm.get((w['lad_code'], normalise(override)))
        if gss is None:
            continue
        council = council_by_lad.get(w['lad_code'])
        if council is None:
            continue
        assign(gss, w['winner'], year_for_all_wards_source(council),
               '2026', 'override')

    # --- Pass 2: current_winners_raw, three-tier per council ---
    scrape_unmatched: list[tuple[str, str]] = []
    for council in for_region('gb'):
        ward_map = raw.get(council['name'])
        if not ward_map:
            continue
        lad = council['lad_code']
        if not lad.startswith(GB_LAD_PREFIXES):
            continue
        for ward_name, rec in ward_map.items():
            gss = geom_by_norm.get((lad, normalise(ward_name)))
            match_type = 'norm'
            if gss is None:
                target = current_overrides.get((council['name'], ward_name))
                if target is not None:
                    gss = geom_by_norm.get((lad, normalise(target)))
                    match_type = 'override'
            if gss is None:
                if len(scrape_unmatched) < 25:
                    scrape_unmatched.append((council['name'], ward_name))
                continue
            assign(gss, rec['party'], rec['year'], 'current_scrape', match_type)

    # --- Output: one record per GB-prefixed geom ward ---
    out: list[dict] = []
    src_counts = {'2026': 0, 'current_scrape': 0, 'none': 0}
    match_counts = {'exact': 0, 'norm': 0, 'override': 0, 'no_match': 0}
    for gss, meta in geom_meta.items():
        rec = assigned.get(gss)
        if rec is None:
            out.append({
                'gss':        gss,
                'lad_code':   meta['lad'],
                'borough':    meta['borough'],
                'ward':       meta['ward'],
                'winner':     None,
                'year':       None,
                'source':     'none',
                'match_type': 'no_match',
            })
            src_counts['none'] += 1
            match_counts['no_match'] += 1
            continue
        out.append({
            'gss':        gss,
            'lad_code':   meta['lad'],
            'borough':    meta['borough'],
            'ward':       meta['ward'],
            **rec,
        })
        src_counts[rec['source']] += 1
        match_counts[rec['match_type']] += 1

    with open(DATA / 'current_winners.json', 'w') as f:
        json.dump(out, f, indent=2)

    print(f'Wrote current_winners.json — {len(out)} GB wards')
    print(f'  by source: 2026={src_counts["2026"]}  '
          f'current_scrape={src_counts["current_scrape"]}  '
          f'none={src_counts["none"]}')
    print(f'  by match:  exact={match_counts["exact"]}  '
          f'norm={match_counts["norm"]}  '
          f'override={match_counts["override"]}  '
          f'no_match={match_counts["no_match"]}')

    # CED-side join — produces data/ced_winners.json for the county-council
    # overlay on the Current map page.
    ced_records, ced_counts = build_ced_winners(geoms)
    with open(DATA / 'ced_winners.json', 'w') as f:
        json.dump(ced_records, f, indent=2)
    print(f'\nWrote ced_winners.json — {len(ced_records)} CEDs '
          f'(matched={ced_counts["matched"]}, no_winner={ced_counts["no_winner"]})')
    if scrape_unmatched:
        print(f'\nFirst {len(scrape_unmatched)} scrape-side unmatched ward(s) '
              '(consider data/source/current_ward_overrides.csv):',
              file=sys.stderr)
        for council, ward in scrape_unmatched:
            print(f'  {council:>30} :: {ward}', file=sys.stderr)


if __name__ == '__main__':
    main()
