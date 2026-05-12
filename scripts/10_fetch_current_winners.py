"""Fetch most-recent-election Wikipedia articles for every council in the
registry that needs one for the Current map page.

Counterpart to scripts/00_fetch_prior_winners.py. Where 00 fetches the *prior*
contest of each 2026-contested council, 10 fetches every article needed to
cover every ward's *most-recent* contest — for councils that didn't have a
2026 contest. The set is driven by `wiki_current_articles` in
data/source/councils.yaml: a list of {year, title} pairs in newest-first
order. For thirds-cycle councils whose last all-out was 2023, the list
typically holds 2025 + 2024 (the two thirds-cycle years that contested the
non-2026 seats); for all-out councils, a single entry pointing at the last
all-out year (e.g. 2022 for Welsh + Scottish councils).

The 134 councils that DID contest in 2026 leave wiki_current_articles: null —
their most-recent winner is already in data/all_wards.json and is sourced
from there at the join step (scripts/04c).

Output: data/source/wiki_current_<council>_<year>.json. Separate filename
namespace from the 00-side wiki_<slug>_<year>.json files so cache
ownership is unambiguous (a 2022 Glasgow article fetched here doesn't
collide with anything fetched by 00). Idempotent — skips files that
already exist.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from _councils import for_region

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
API = 'https://en.wikipedia.org/w/api.php'


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def fetch(title: str) -> dict:
    qs = urllib.parse.urlencode({
        'action': 'parse',
        'page': title,
        'format': 'json',
        'formatversion': '2',
        'prop': 'wikitext',
        'redirects': '1',
    })
    req = urllib.request.Request(f'{API}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    fetched = skipped = 0
    misses: list[tuple[str, str, str]] = []  # (lad_code, name, attempted_title)
    for council in for_region("gb"):
        articles = council.get("wiki_current_articles")
        if not articles:
            continue
        for entry in articles:
            year = entry["year"]
            title = entry["title"]
            out = SOURCE / f'wiki_current_{slug(council["name"])}_{year}.json'
            if out.exists():
                skipped += 1
                continue
            print(f'Fetching {title}...')
            data = fetch(title)
            if 'error' in data:
                print(f'  ! {data["error"].get("code")}: {data["error"].get("info", "")}')
                misses.append((council["lad_code"], council["name"], title))
                time.sleep(0.5)
                continue
            with open(out, 'w') as f:
                json.dump(data, f)
            fetched += 1
            time.sleep(0.5)  # be nice to Wikipedia

    print(f'\nDone. Fetched {fetched}, skipped {skipped} (already cached), {len(misses)} miss(es).')
    if misses:
        print("\nMisses — update wiki_current_articles in data/source/councils.yaml for these:")
        for lad, name, tried in misses:
            print(f'  {lad}  {name}: tried "{tried}"')


if __name__ == '__main__':
    main()
