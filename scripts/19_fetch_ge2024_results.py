"""Fetch Wikipedia results articles for the 4 July 2024 UK General Election
(one per parliamentary constituency in the PCON_JUL_2024 boundary set).

Sibling to scripts/14_fetch_senedd_results.py: ~650 idempotent fetches against
the Wikipedia API, one cache file per article, 0.5 s between requests so we
stay polite. Subsequent runs short-circuit on the cached files.

Output: one cache file per Wikipedia article,
data/source/wiki_ge2024_<slug>.json — the wiki_*.json glob in .gitignore covers
these (re-fetchable on first run of a fresh clone, ~5–6 min one-off).

NI seats (N05*) are fetched too — the GB/NI scope decision happens at render
time in 07d, so the cache here is complete and a future NI render needs no
re-fetch.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from _ge2024_constituencies import GE2024_CONSTITUENCIES

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
API = 'https://en.wikipedia.org/w/api.php'

TITLES = [t for (_c, _n, t) in GE2024_CONSTITUENCIES]


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
    misses: list[str] = []
    for i, title in enumerate(TITLES, start=1):
        out = SOURCE / f'wiki_ge2024_{slug(title)}.json'
        if out.exists():
            skipped += 1
            continue
        print(f'[{i}/{len(TITLES)}] Fetching {title}...')
        data = fetch(title)
        if 'error' in data:
            print(f'  ! {data["error"].get("code")}: {data["error"].get("info", "")}')
            misses.append(title)
            time.sleep(0.5)
            continue
        with open(out, 'w') as f:
            json.dump(data, f)
        fetched += 1
        time.sleep(0.5)  # be nice to Wikipedia

    print(f'\nDone. Fetched {fetched}, skipped {skipped} (already cached), {len(misses)} miss(es).')
    if misses:
        print("\nMisses — confirm the Wikipedia article title for these:")
        for t in misses:
            print(f'  "{t}"')


if __name__ == '__main__':
    main()
