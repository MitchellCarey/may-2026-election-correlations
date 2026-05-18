"""Build the per-ward per-year history dataset for the Current map page's
time slider (issue #70 / #69 phase 1A).

Sibling of scripts/04c_build_current_winners.py. Where 04c collapses every
ward to a single most-recent record, 04d keeps the full per-year history
for each ward so the slider can rewind from 2026 back to 2018.

Sources (in per-(gss, year) precedence — mirrors 04c's per-record order):
  1. data/source/ward_official_<year>.csv — authoritative council results
  2. data/all_wards.json (year = year_for_all_wards_source(council)) — wiki
     2026 baseline for the 134 councils that contested 2026
  3. wiki_current_articles parsed by scripts/_wiki_history — every prior
     contest of the council that has a cached article

Two-pass name match identical to 04c:
  pass 1 — normalised (lad, ward) → WD24CD lookup
  pass 2 — walk ward_name_overrides.csv (1a) or current_ward_overrides.csv (1b)
           and retry the normalised lookup. N:1 overrides paint multiple
           WD24 polygons from one scraped ward (post-2025 boundary-review
           unitaries like Durham / Bucks).

Each history entry carries a `url` field pointing to where the result was
sourced (Wikipedia article URL, official council results URL), so the
slider tooltip can let readers click through to verify accuracy and
report errors. The schema extension is per user request mid-implementation
of issue #70 — see the plan in /Users/mitch/.claude/plans/.

Output: data/ward_history.json — { "years": [...], "wards": { gss: {
  borough, ward, history: [ {y, w, src, url} ... ascending by year ] } } }

Determinism: sort_keys=True on json.dump, gss-sorted ward iteration, year-
sorted history entries within each ward.
"""
import csv
import json
import sys
import urllib.parse
from pathlib import Path

from _councils import for_region
from _wiki_history import iter_council_year_records, pick_parser

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"

# GB-only — mirrors 04c.
GB_LAD_PREFIXES = ('E06', 'E07', 'E08', 'E09', 'W06', 'S12')

# Years the slider exposes. 2020 deferred to 2021 under the Coronavirus
# postponement regulations; no entries useful at that year.
SLIDER_YEARS = [2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]


def wikipedia_url(title: str) -> str:
    """Canonical Wikipedia URL for an article title. Spaces → underscores;
    other characters URL-encoded so e.g. parentheses + apostrophes survive
    the round-trip without breaking the link."""
    return f'https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(" ", "_"), safe="_,()/")}'


def import_04c():
    """Import 04c's helpers (normalise, load_geom_overrides, etc.) without
    duplicating ~50 lines of code. 04c isn't a package — load it as a module
    by inserting its directory on sys.path."""
    sys.path.insert(0, str(ROOT / "scripts"))
    # __import__ avoids leading-digit module-name awkwardness — 04c lives at
    # `04c_build_current_winners` which is a valid filename but not a valid
    # Python identifier (digits-first). importlib handles it cleanly.
    import importlib
    return importlib.import_module('04c_build_current_winners')


def main():
    h04c = import_04c()
    normalise = h04c.normalise
    load_geom_overrides = h04c.load_geom_overrides
    load_current_overrides = h04c.load_current_overrides
    year_for_all_wards_source = h04c.year_for_all_wards_source

    with open(DATA / 'all_wards.json') as f:
        all_wards = json.load(f)
    with open(DATA / 'ward_geoms.json') as f:
        geoms = json.load(f)

    council_by_lad = {c['lad_code']: c for c in for_region('gb')}
    council_by_name = {c['name']: c for c in for_region('gb')}
    geom_overrides = load_geom_overrides()
    current_overrides = load_current_overrides()

    # Geom-side lookup — mirrors 04c.
    geom_by_norm: dict[tuple[str, str], str] = {}
    geom_meta: dict[str, dict] = {}
    for gss, w in geoms['wards'].items():
        lad = w['lad']
        if not lad.startswith(GB_LAD_PREFIXES):
            continue
        borough = geoms['boroughs'].get(lad, {}).get('name', '')
        geom_by_norm[(lad, normalise(w['name']))] = gss
        geom_meta[gss] = {'lad': lad, 'borough': borough, 'ward': w['name']}

    # history: gss → {year: entry} — first-write-wins within each (gss, year).
    history: dict[str, dict[int, dict]] = {}

    def assign(gss: str, year: int, party: str, src: str, url: str) -> bool:
        per_ward = history.setdefault(gss, {})
        if year in per_ward:
            return False
        per_ward[year] = {'y': year, 'w': party, 'src': src, 'url': url}
        return True

    # --- Pass 0: ward_official_<year>.csv — authoritative per (gss, year) ---
    official_paths = sorted(SOURCE.glob('ward_official_*.csv'))
    pass0_added = 0
    for path in official_paths:
        m = path.stem.split('_')[-1]
        try:
            year = int(m)
        except ValueError:
            continue
        with open(path, newline='') as f:
            for row in csv.DictReader(f):
                if not row.get('party') or not row.get('ward'):
                    continue
                lad = row['lad_code']
                if not lad.startswith(GB_LAD_PREFIXES):
                    continue
                council = council_by_lad.get(lad)
                official_url = (council or {}).get('official_url') or ''
                gss = geom_by_norm.get((lad, normalise(row['ward'])))
                if gss is None:
                    override = geom_overrides.get((lad, row['ward']))
                    if override is not None:
                        gss = geom_by_norm.get((lad, normalise(override)))
                if gss is None:
                    continue
                if assign(gss, year, row['party'], 'official_ward', official_url):
                    pass0_added += 1

    # --- Pass 1: all_wards.json — the council's most-recent contest, year-
    #     tagged via year_for_all_wards_source (typically 2026). ---
    pass1_added = 0
    for w in all_wards:
        if not w.get('winner'):
            continue
        lad = w['lad_code']
        if not lad.startswith(GB_LAD_PREFIXES):
            continue
        council = council_by_lad.get(lad)
        if council is None:
            continue
        year = year_for_all_wards_source(council)
        gss = geom_by_norm.get((lad, normalise(w['ward'])))
        if gss is None:
            override = geom_overrides.get((lad, w['ward']))
            if override is not None:
                gss = geom_by_norm.get((lad, normalise(override)))
        if gss is None:
            continue
        # URL: only use wiki_2026 / wiki_prior when the article's year
        # matches the entry's year AND every ward in all_wards.json for
        # this council contested that year. Thirds councils elect one seat
        # in every ward each year, so all_wards.json's 2026 entries all
        # appear in the wiki_2026 article (see year_for_all_wards_source in
        # 04c). Halves councils contest only half their wards in 2026, so
        # the council-level article wouldn't list every ward — leave the
        # URL empty there and let Pass 2's per-contest-year entries supply
        # URLs at earlier slider stops.
        cycle = council.get('cycle')
        all_wards_in_one_year = cycle in ('all-out', 'thirds')
        if (year == 2026 and council.get('wiki_2026')
                and all_wards_in_one_year):
            url = wikipedia_url(council['wiki_2026'])
        elif (year == council.get('wiki_prior_year')
                and council.get('wiki_prior')
                and all_wards_in_one_year):
            url = wikipedia_url(council['wiki_prior'])
        else:
            url = ''
        if assign(gss, year, w['winner'], 'all_wards', url):
            pass1_added += 1

    # --- Pass 2: wiki_current_articles — every prior contest with a
    #     cached article, walked via _wiki_history. ---
    pass2_added = 0
    pass2_unmatched_count = 0
    pass2_unmatched_sample: list[tuple[str, str, int]] = []
    pass2_unmatched_by_council: dict[str, int] = {}
    article_titles_by_council_year: dict[tuple[str, int], str] = {}
    for council in for_region('gb'):
        for entry in (council.get('wiki_current_articles') or []):
            article_titles_by_council_year[(council['name'], entry['year'])] = entry['title']

    for council in for_region('gb'):
        lad = council['lad_code']
        if not lad.startswith(GB_LAD_PREFIXES):
            continue
        _parser, is_county = pick_parser(council)
        if is_county:
            continue  # CED-side; not part of ward history
        for year, ward_name, rec in iter_council_year_records(council):
            party = rec.get('prior_party')
            if not party:
                continue
            url_title = article_titles_by_council_year.get((council['name'], year), '')
            url = wikipedia_url(url_title) if url_title else ''
            matched_any = False
            direct_gss = geom_by_norm.get((lad, normalise(ward_name)))
            if direct_gss is not None:
                if assign(direct_gss, year, party, 'wiki', url):
                    pass2_added += 1
                matched_any = True
            for target in current_overrides.get((council['name'], ward_name), []):
                target_gss = geom_by_norm.get((lad, normalise(target)))
                if target_gss is None:
                    continue
                if assign(target_gss, year, party, 'wiki', url):
                    pass2_added += 1
                matched_any = True
            if not matched_any:
                pass2_unmatched_count += 1
                pass2_unmatched_by_council[council['name']] = (
                    pass2_unmatched_by_council.get(council['name'], 0) + 1
                )
                if len(pass2_unmatched_sample) < 25:
                    pass2_unmatched_sample.append((council['name'], ward_name, year))

    # --- Output assembly: stable sort, per-ward history ascending by year ---
    out_wards: dict[str, dict] = {}
    for gss, meta in geom_meta.items():
        per_year = history.get(gss, {})
        entries = sorted(per_year.values(), key=lambda e: e['y'])
        out_wards[gss] = {
            'borough': meta['borough'],
            'ward':    meta['ward'],
            'history': entries,
        }

    # Year stops the slider exposes. Restricted to SLIDER_YEARS (2018-2026
    # per the phase 1A spec) — pre-2018 entries STAY in WARD_HISTORY so
    # paintAtYear's carry-forward works at year=2018 for thirds wards whose
    # last contest was 2017 or earlier. The slider just doesn't let users
    # scrub to those earlier stops in phase 1A.
    all_years_in_data = {e['y'] for entries in out_wards.values()
                          for e in entries['history']}
    present_years = sorted(set(SLIDER_YEARS) & all_years_in_data | {2026})

    out = {
        'years': present_years,
        'wards': out_wards,
    }
    with open(DATA / 'ward_history.json', 'w') as f:
        json.dump(out, f, sort_keys=True, separators=(',', ':'))

    # Summary line — mirrors 04c's discipline + the project's memory about
    # surfacing silent join failures with WARNs.
    total_wards = len(out_wards)
    total_ward_years = sum(len(w['history']) for w in out_wards.values())
    per_year_coverage: dict[int, int] = {}
    for w in out_wards.values():
        for e in w['history']:
            per_year_coverage[e['y']] = per_year_coverage.get(e['y'], 0) + 1
    print(f'Wrote ward_history.json — {total_wards:,} wards, {len(present_years)} year stops, '
          f'{total_ward_years:,} ward-years')
    print(f'  passes: 0={pass0_added:,} (ward_official), '
          f'1={pass1_added:,} (all_wards), 2={pass2_added:,} (wiki)')
    print('  per-year coverage: ' + ' · '.join(
        f'{y}: {per_year_coverage.get(y, 0):,}' for y in present_years
    ))
    if pass2_unmatched_count:
        top_councils = sorted(pass2_unmatched_by_council.items(),
                              key=lambda kv: -kv[1])[:10]
        per_council = ', '.join(f'{name}={n}' for name, n in top_councils)
        print(f'  pass 2: {pass2_unmatched_count:,} council/ward/year tuples unmatched '
              f'across {len(pass2_unmatched_by_council)} councils '
              f'(top 10: {per_council}; showing first {len(pass2_unmatched_sample)}):',
              file=sys.stderr)
        for name, ward, year in pass2_unmatched_sample:
            print(f'    {year} {name}: "{ward}"', file=sys.stderr)


if __name__ == '__main__':
    main()
