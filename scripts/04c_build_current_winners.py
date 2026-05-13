"""Build the per-ward "current winner" dataset for the Current map page.

Joins four sources onto the WD24 ward geometry to produce one record per
GB ward (England + Wales + Scotland; NI omitted):

  1. data/source/ward_official_<year>.csv — per-ward winners scraped (or
                                       hand-curated) from each council's
                                       own results page. Authoritative;
                                       outranks the other sources per-row.
  2. data/all_wards.json            — the 134 councils that contested 2026.
                                       For these, "current" = the 2026 winner
                                       already in `winner`.
  3. data/current_winners_raw.json  — the non-2026 councils, per-ward most-
                                       recent winners scraped by 10+11.
  4. data/ward_geoms.json           — source of truth for the ward identity
                                       (gss code, WD24 name, borough LAD).

Per-record precedence: source 1 (per row, if the (lad, ward) joins to a
WD24 polygon) → source 2 (if the LAD appears in all_wards.json with a
non-null winner for this ward) → source 3 (current_winners_raw, by council
name + ward name via the three-tier matcher) → null.

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


def load_current_overrides() -> dict[tuple[str, str], list[str]]:
    """Optional (council_name, scraped_name) → [gss_name, ...] overrides
    scoped to the Current scrape. Two cases:

      - 1:1 — Welsh/Scottish pre-2024 name drift (one scraped name → one
              WD24 ward).
      - N:1 — boundary-review unitaries (Durham, Bucks, etc.) where one
              post-review scraped ward absorbed two or more pre-review
              WD24 wards. Same scraped_name appears on multiple rows; each
              row contributes one WD24 target.

    Missing file returns {}."""
    path = SOURCE / 'current_ward_overrides.csv'
    if not path.exists():
        return {}
    overrides: dict[tuple[str, str], list[str]] = {}
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            key = (row['council'], row['scraped_name'])
            overrides.setdefault(key, []).append(row['gss_name'])
    return overrides


def load_ced_overrides() -> dict[tuple[str, str], str]:
    """(cty_code, normalised ONS CED name) → normalised CSV division name.

    Bridges the divergence between the ONS CED25 polygon set (pre-2025
    boundary review names like 'Fakenham ED') and the post-review division
    names councils publish ('Fakenham and The Raynhams'). Mirrors the role
    of ward_name_overrides.csv for ward-level WD24 boundary-review drift —
    but applied geometry → result (the CED join iterates polygons first),
    so the override translates the ONS name into the CSV name we need to
    look up. Missing file returns {}.

    Schema: cty_code, ons_name, csv_division, note.
    """
    path = SOURCE / 'ced_name_overrides.csv'
    if not path.exists():
        return {}
    overrides: dict[tuple[str, str], str] = {}
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            key = (row['cty_code'], normalise_ced(row['ons_name']))
            overrides[key] = normalise_ced(row['csv_division'])
    return overrides


def load_county_official(year: int) -> dict[str, dict[str, dict]]:
    """Read data/source/county_official_<year>.csv — authoritative per-CED
    winners scraped (or hand-curated) from each council's own results page.
    Indexed by county name → normalised CED name → record. Highest-priority
    source for that year's CEDs; overrides Wikipedia in build_ced_winners().

    CSV schema: lad_code, county, division, party, candidate, votes, source.
    Missing file is fine — returns {}.

    Phase 1 populated the 2026 file (Norfolk, hand-curated). Phase 2 of
    issue #9 adds the rest of the 6 × 2026 counties via scripts/13. Phase 3
    populates county_official_2025.csv via the same dispatcher.
    """
    path = SOURCE / f'county_official_{year}.csv'
    if not path.exists():
        return {}
    out: dict[str, dict[str, dict]] = {}
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            out.setdefault(row['county'], {})[normalise_ced(row['division'])] = {
                'party': row['party'],
                'year':  year,
                'source_ced_name': row['division'],
            }
    return out


def load_ward_official(year: int) -> dict[str, list[dict]]:
    """Read data/source/ward_official_<year>.csv — authoritative per-ward
    winners scraped (or hand-curated) from each council's own results page.
    Indexed by lad_code → list of records (preserves per-council row counts
    so coverage M/N can be reported per council, including misses). Highest-
    priority ward source; outranks both all_wards.json (2026 councils) and
    current_winners_raw.json (non-2026 councils) in main().

    CSV schema: lad_code, council, ward, party, candidate, votes, source.
    Missing file is fine — returns {}.
    """
    path = SOURCE / f'ward_official_{year}.csv'
    if not path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            if not row.get('party') or not row.get('ward'):
                continue
            out.setdefault(row['lad_code'], []).append({
                'council': row['council'],
                'ward':    row['ward'],
                'party':   row['party'],
                'year':    year,
            })
    return out


def build_ced_winners(geoms: dict) -> list[dict]:
    """Join CED-level winners onto the CED25 polygons in ward_geoms.json.
    One record per CED25CD with winner / year / county.

    Source precedence is per-county, not per-record:
      1. data/source/county_official_2026.csv — hand-curated authoritative
         data from each council's own results page. Always wins where set.
      2. county_results_2026_ceds.json — Wikipedia 2026 parsings (partly
         placeholder while editors catch up post-election).
      3. current_ced_winners_raw.json — the 14 × 2025 contested counties.
      4. county_results_prior_ceds.json — 2021 priors, used only for
         counties not present in 1/2/3.

    For a county that appears in source 1 or 2, source 4 (2021 priors) is
    intentionally NOT consulted — the 2026 election superseded 2021 even
    where specific CEDs aren't yet published.
    """
    official_2026 = load_county_official(2026)
    ced_overrides = load_ced_overrides()
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
    all_counties = set(official_2026) | set(data_2026) | set(data_curr) | set(data_prior)
    for county_name in all_counties:
        if county_name in official_2026 or county_name in data_2026:
            # Merge official over Wikipedia — official wins on every CED it covers,
            # Wikipedia fills in the rest (e.g. East Sussex 50/50 in Wiki, no
            # official rows; Norfolk 84/84 in official, Wiki not consulted).
            merged = index(data_2026.get(county_name, {}))
            merged.update(official_2026.get(county_name, {}))
            by_county_norm[county_name] = merged
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

    counted = {'matched': 0, 'override': 0, 'no_winner': 0}
    used_keys: dict[str, set[str]] = {}
    for ced_code, meta in geoms.get('ceds', {}).items():
        cty_clean = by_cty_norm_to_county_name.get(meta.get('cty', ''), '')
        ced_county_data = by_county_norm.get(cty_clean, {})
        key = normalise_ced(meta['name'])
        rec = ced_county_data.get(key)
        matched_key = key
        if rec is None:
            override_key = ced_overrides.get((meta.get('cty', ''), key))
            if override_key is not None:
                rec = ced_county_data.get(override_key)
                if rec is not None:
                    counted['override'] += 1
                    matched_key = override_key
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
            used_keys.setdefault(cty_clean, set()).add(matched_key)
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

    # Validate that every override row points to a real CSV division. A typo
    # in csv_division would silently miss (no exception, just unpainted) — flag
    # it explicitly to stderr so editors see broken rows on the next 04c run.
    for (cty_code, ons_key), csv_key in ced_overrides.items():
        county_name = by_cty_norm_to_county_name.get(cty_code, '')
        if not county_name:
            continue
        if csv_key not in by_county_norm.get(county_name, {}):
            print(f'WARNING: ced_name_overrides.csv: {county_name} '
                  f'"{ons_key}" → "{csv_key}" — target not in result data '
                  f'(typo? or 2025-county data not loaded)', file=sys.stderr)

    # Source-side rows that didn't join to any ONS polygon — usually a sign
    # of a boundary review the ONS CED25 set predates (Essex May 2026), or a
    # name-normalisation drift. Print so the gap is visible in build logs.
    for county, ced_county_data in by_county_norm.items():
        unmatched = sorted(set(ced_county_data) - used_keys.get(county, set()))
        if not unmatched:
            continue
        sample = ', '.join(ced_county_data[k]['source_ced_name'] for k in unmatched[:3])
        more = '' if len(unmatched) <= 3 else f' (+{len(unmatched) - 3} more)'
        print(f'  WARN {county}: {len(unmatched)} source CED name(s) had no '
              f'ONS CED25 match — e.g. {sample}{more}', file=sys.stderr)
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

    # --- Pass 0: ward_official_<year>.csv (authoritative; outranks every other ward source) ---
    # Per-LAD (matched, total, unmatched_wards) — feeds the per-council
    # "Norfolk 84/84 in official" coverage lines + stderr WARNs for rows
    # that didn't join to a WD24 polygon.
    ward_official = load_ward_official(2026)
    official_stats: list[tuple[str, str, int, int, list[str]]] = []
    for lad in sorted(ward_official):
        rows = ward_official[lad]
        council_name = rows[0]['council']
        matched = 0
        unmatched: list[str] = []
        for row in rows:
            match_type = 'exact'
            gss = geom_by_norm.get((lad, normalise(row['ward'])))
            if gss is None:
                override = geom_overrides.get((lad, row['ward']))
                if override is not None:
                    gss = geom_by_norm.get((lad, normalise(override)))
                    match_type = 'override'
            if gss is None:
                unmatched.append(row['ward'])
                continue
            if assign(gss, row['party'], row['year'], 'official_ward', match_type):
                matched += 1
        official_stats.append((lad, council_name, matched, len(rows), unmatched))

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
            matched_any = False
            direct_gss = geom_by_norm.get((lad, normalise(ward_name)))
            if direct_gss is not None:
                assign(direct_gss, rec['party'], rec['year'],
                       'current_scrape', 'norm')
                matched_any = True
            # Overrides are additive, not fallback — a 2025 post-review
            # ward whose name still matches a WD24 polygon (e.g.
            # "Chester-le-Street North") also paints the WD24 polygons
            # of the pre-review wards it absorbed. For older 1:1
            # name-drift rows the direct lookup misses and only the
            # override target fires; behaviour unchanged.
            for target in current_overrides.get((council['name'], ward_name), []):
                target_gss = geom_by_norm.get((lad, normalise(target)))
                if target_gss is None:
                    print(f'WARNING: current_ward_overrides.csv: {council["name"]} '
                          f'"{ward_name}" → "{target}" — target not a WD24 ward '
                          f'in {lad} (typo? boundary review?)', file=sys.stderr)
                    continue
                assign(target_gss, rec['party'], rec['year'],
                       'current_scrape', 'override')
                matched_any = True
            if not matched_any and len(scrape_unmatched) < 25:
                scrape_unmatched.append((council['name'], ward_name))

    # CED-side join — produces data/ced_winners.json for the county-council
    # overlay on the Current map page. Run before the per-ward output so the
    # ward records can pick up their parent-CED context for the tooltip
    # quick-win (issue #8 acceptance 3).
    ced_records, ced_counts = build_ced_winners(geoms)
    with open(DATA / 'ced_winners.json', 'w') as f:
        json.dump(ced_records, f, indent=2)
    print(f'Wrote ced_winners.json — {len(ced_records)} CEDs '
          f'(matched={ced_counts["matched"]} '
          f'[incl. override={ced_counts["override"]}], '
          f'no_winner={ced_counts["no_winner"]})')

    # Per-ward CED enrichment: every WD25 ward in a 2-tier English district
    # gets its parent CED's winner attached, so hovering the ward on the
    # Current page surfaces who controls schools/social-care/roads there.
    # WD25CD ≈ WD24CD for any ward without a 2024→2025 boundary review (none
    # known in 2-tier shire districts); wards that don't resolve are silently
    # skipped and fall through to a ward-only tooltip.
    ced_by_code = {r['ced']: r for r in ced_records}
    ward_to_ced = geoms.get('ward_to_ced', {})
    ced_context: dict[str, dict] = {}
    for wd, ced in ward_to_ced.items():
        if wd not in geom_meta:
            continue
        rec = ced_by_code.get(ced)
        if not rec:
            continue
        ced_context[wd] = {
            'ced_county': rec['county'],
            'ced_name':   rec['name'],
            'ced_winner': rec['winner'],
            'ced_year':   rec['year'],
        }

    # --- Output: one record per GB-prefixed geom ward ---
    out: list[dict] = []
    src_counts = {'official_ward': 0, '2026': 0, 'current_scrape': 0, 'none': 0}
    match_counts = {'exact': 0, 'norm': 0, 'override': 0, 'no_match': 0}
    for gss, meta in geom_meta.items():
        rec = assigned.get(gss)
        ced_extra = ced_context.get(gss, {})
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
                **ced_extra,
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
            **ced_extra,
        })
        src_counts[rec['source']] += 1
        match_counts[rec['match_type']] += 1

    with open(DATA / 'current_winners.json', 'w') as f:
        json.dump(out, f, indent=2)

    print(f'Wrote current_winners.json — {len(out)} GB wards')
    print(f'  by source: official_ward={src_counts["official_ward"]}  '
          f'2026={src_counts["2026"]}  '
          f'current_scrape={src_counts["current_scrape"]}  '
          f'none={src_counts["none"]}')
    print(f'  by match:  exact={match_counts["exact"]}  '
          f'norm={match_counts["norm"]}  '
          f'override={match_counts["override"]}  '
          f'no_match={match_counts["no_match"]}')
    n_off_councils = len(official_stats)
    n_off_wards = sum(m for _, _, m, _, _ in official_stats)
    print(f'  ward official: {n_off_councils} councils, {n_off_wards} wards')
    for _, council_name, matched, total, _unm in official_stats:
        print(f'    {council_name} {matched}/{total} in official')
    for _, council_name, _matched, _total, unmatched in official_stats:
        if not unmatched:
            continue
        sample = ', '.join(unmatched[:3])
        more = '' if len(unmatched) <= 3 else f' (+{len(unmatched) - 3} more)'
        print(f'  WARN {council_name}: {len(unmatched)} ward(s) in '
              f'ward_official_2026.csv had no WD24 match — '
              f'e.g. {sample}{more}', file=sys.stderr)
    with_ced = sum(1 for r in out if r.get('ced_county'))
    counties_seen = {r['ced_county'] for r in out if r.get('ced_county')}
    print(f'  with CED context: {with_ced} wards across {len(counties_seen)} counties')
    if scrape_unmatched:
        print(f'\nFirst {len(scrape_unmatched)} scrape-side unmatched ward(s) '
              '(consider data/source/current_ward_overrides.csv):',
              file=sys.stderr)
        for council, ward in scrape_unmatched:
            print(f'  {council:>30} :: {ward}', file=sys.stderr)


if __name__ == '__main__':
    main()
