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
import re
from pathlib import Path

from _councils import for_region
from _wiki_parser import parse_article, parse_stv_article

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main():
    all_winners: dict[str, dict[str, dict]] = {}
    summary_rows = []
    missing_cache = []
    for council in for_region("gb"):
        articles = council.get("wiki_current_articles")
        if not articles:
            continue
        name = council["name"]
        system = council.get("electoral_system", "fptp")
        parser = parse_stv_article if system == "stv" else parse_article

        ward_map: dict[str, dict] = {}
        for entry in articles:  # newest-first
            year = entry["year"]
            path = SOURCE / f'wiki_current_{slug(name)}_{year}.json'
            if not path.exists():
                missing_cache.append((council["lad_code"], name, year))
                continue
            with open(path) as f:
                wt = json.load(f)['parse']['wikitext']
            parsed = parser(name, year, wt)
            for ward, rec in parsed.items():
                if ward in ward_map:
                    continue
                ward_map[ward] = {'party': rec['prior_party'], 'year': rec['prior_year']}

        all_winners[name] = ward_map
        counts: dict[str, int] = {}
        for w in ward_map.values():
            counts[w['party']] = counts.get(w['party'], 0) + 1
        summary_rows.append((name, system, len(ward_map), counts))

    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / 'current_winners_raw.json', 'w') as f:
        json.dump(all_winners, f, indent=2)

    total_wards = sum(len(v) for v in all_winners.values())
    print(f'Saved current_winners_raw.json — {total_wards} wards across '
          f'{len(all_winners)} councils')
    if missing_cache:
        print(f'  ({len(missing_cache)} council/year pairs in registry but no cached file; '
              f'run scripts/10_fetch_current_winners.py)')
    print()
    for name, system, n, counts in summary_rows:
        print(f'  {name:>30} [{system:>4}]: {n:>3} wards | {counts}')


if __name__ == '__main__':
    main()
