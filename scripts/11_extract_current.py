"""Parse cached Wikipedia wikitext into per-ward most-recent winners for
the Current map page.

Reads data/source/wiki_current_<slug>_<year>.json (produced by 10) for every
council in data/source/councils.yaml with a non-null `wiki_current_articles`
list, and writes data/current_winners_raw.json:

    { council_name: { ward_name: { party, year } } }

For each council the list is walked **newest first**; the first time a ward
name appears, that record wins. This gives per-seat last-contest semantics
for thirds councils — a ward contested in 2025 takes its 2025 winner; a
sibling ward that wasn't up in 2025 falls through to the 2024 winner.

Parser dispatch is keyed on `electoral_system`:
  fptp → reuse scripts/_wiki_parser.parse_article
  stv  → scripts/_wiki_parser.parse_stv_article (Scottish councils)

Councils with `wiki_current_articles: null` are skipped — those are the 134
that contested 2026, and their winner is sourced from data/all_wards.json
at the join step (04c).
"""
import json
from pathlib import Path

from _councils import for_region
from _wiki_history import iter_council_year_records, iter_missing_cache, pick_parser

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def main():
    all_winners: dict[str, dict[str, dict]] = {}
    ced_winners: dict[str, dict[str, dict]] = {}  # parallel output for E10 counties
    summary_rows = []
    missing_cache = []
    for council in for_region("gb"):
        articles = council.get("wiki_current_articles")
        if not articles:
            continue
        name = council["name"]
        system = council.get("electoral_system", "fptp")
        _, is_county = pick_parser(council)
        for year, _path in iter_missing_cache(council):
            missing_cache.append((council["lad_code"], name, year))

        # Newest-first collapse: the first record to claim a ward key wins,
        # preserving per-seat last-contest semantics for thirds councils.
        ward_map: dict[str, dict] = {}
        for _year, key, rec in iter_council_year_records(council):
            if key in ward_map:
                continue
            if is_county:
                # CED parser returns {ced: {party, district, year}}; keep
                # the district context for downstream UX (tooltip / drilldown).
                ward_map[key] = {'party': rec['party'], 'year': rec['year'],
                                 'district': rec.get('district')}
            else:
                ward_map[key] = {'party': rec['prior_party'], 'year': rec['prior_year']}

        target = ced_winners if is_county else all_winners
        target[name] = ward_map
        counts: dict[str, int] = {}
        for w in ward_map.values():
            counts[w['party']] = counts.get(w['party'], 0) + 1
        kind = 'ceds' if is_county else system
        summary_rows.append((name, kind, len(ward_map), counts))

    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / 'current_winners_raw.json', 'w') as f:
        json.dump(all_winners, f, indent=2)
    with open(DATA / 'current_ced_winners_raw.json', 'w') as f:
        json.dump(ced_winners, f, indent=2)

    total_wards = sum(len(v) for v in all_winners.values())
    total_ceds = sum(len(v) for v in ced_winners.values())
    print(f'Saved current_winners_raw.json — {total_wards} wards across '
          f'{len(all_winners)} councils')
    print(f'Saved current_ced_winners_raw.json — {total_ceds} CEDs across '
          f'{len(ced_winners)} county councils')
    if missing_cache:
        print(f'  ({len(missing_cache)} council/year pairs in registry but no cached file; '
              f'run scripts/10_fetch_current_winners.py)')
    print()
    for name, system, n, counts in summary_rows:
        print(f'  {name:>30} [{system:>4}]: {n:>3} wards | {counts}')


if __name__ == '__main__':
    main()
