"""Parse cached Wikipedia wikitext into per-ward prior winners.

Reads data/source/wiki_<slug>_<year>.json (produced by 00) for every council
in data/source/councils.yaml with a wiki_prior set, and writes
data/prior_winners.json:

    { council_name: { ward_name: { prior_party, prior_year } } }

We use the **top-of-poll party** as "prior winner" — i.e. the first
`{{Election box winning candidate with party link...}}` template within each
ward's wikitext section. This works uniformly for:

- Thirds boroughs in 2022 where only one seat per ward was up (one winning
  candidate template per ward — that's the seat).
- All-out boroughs (Bury, Rochdale 2022 post-boundary; Salford 2021;
  every London borough 2022) where three winning candidates were elected
  per ward — Wikipedia lists them in vote-rank order, so the first template
  is top-of-poll.

This matches how the existing 2026 dataset records Salford winners (top of
poll), so the prior-vs-2026 comparison is apples-to-apples.

Wigan 2022 organises wards as h4 inside h3 constituency sections, so we collect
both heading levels.
"""
import json
import re
from pathlib import Path

from _councils import for_region
from _wiki_parser import parse_article, parse_county_article

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

def main():
    all_winners = {}
    counties_out = {}
    summary_rows = []
    counties_summary = []
    missing_cache = []
    for council in for_region("gb"):
        if not council.get("wiki_prior"):
            continue
        name = council["name"]
        year = council["wiki_prior_year"]
        path = SOURCE / f'wiki_{slug(name)}_{year}.json'
        if not path.exists():
            missing_cache.append((council["lad_code"], name, year))
            continue
        with open(path) as f:
            wt = json.load(f)['parse']['wikitext']
        # English county councils (E10*) — see 01c for rationale; aggregate
        # by district rather than parsing per-ward.
        if council["lad_code"].startswith("E10"):
            districts = parse_county_article(name, year, wt)
            counties_out[name] = districts
            counts = {}
            for d in districts.values():
                counts[d['party']] = counts.get(d['party'], 0) + 1
            counties_summary.append((name, year, len(districts), counts))
            continue
        winners = parse_article(name, year, wt)
        all_winners[name] = winners
        counts = {}
        for w in winners.values():
            counts[w['prior_party']] = counts.get(w['prior_party'], 0) + 1
        summary_rows.append((name, year, len(winners), counts))

    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / 'prior_winners.json', 'w') as f:
        json.dump(all_winners, f, indent=2)
    with open(DATA / 'county_results_prior.json', 'w') as f:
        json.dump(counties_out, f, indent=2)

    total_wards = sum(len(v) for v in all_winners.values())
    cty_total = sum(len(v) for v in counties_out.values())
    print(f'Saved prior_winners.json — {total_wards} wards across {len(all_winners)} councils')
    print(f'Saved county_results_prior.json — {cty_total} districts across {len(counties_out)} counties')
    if missing_cache:
        print(f'  ({len(missing_cache)} councils have wiki_prior but no cached file; run scripts/00_fetch_prior_winners.py)')
    print()
    for name, year, n, counts in summary_rows:
        print(f'  {name:>30} ({year}): {n:>3} wards | {counts}')
    print()
    for name, year, n, counts in counties_summary:
        print(f'  {name:>30} ({year}): {n:>3} districts | {counts}')


if __name__ == '__main__':
    main()
