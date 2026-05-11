"""Fetch 2026 council-election Wikipedia articles for every registry row
with a non-null wiki_2026.

Mirror of scripts/00_fetch_prior_winners.py for the current election. Each
row in data/source/councils.yaml with wiki_2026 set names the article to
fetch; rows with wiki_2026: null are skipped (typically a GM borough whose
hand-curated results live in data/source/results_2026.csv, or a council
with no 2026 contest like the Welsh and Scottish areas).

Output: data/source/wiki_<council-slug>_2026.json (raw MediaWiki API
response). Idempotent — skips files that already exist.

On a Wikipedia 404 the script continues and reports the miss at the end,
so a batch of registry additions can be validated in one pass. Fix the
wiki_2026 entry in councils.yaml and rerun; the cached successes don't
re-fetch.
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
    """Council name -> filesystem-safe slug for the wiki cache filename."""
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
    misses: list[tuple[str, str, str]] = []
    for council in for_region("gb"):
        if not council.get("wiki_2026"):
            continue
        title = council["wiki_2026"]
        out = SOURCE / f'wiki_{slug(council["name"])}_2026.json'
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
        time.sleep(0.5)

    print(f'\nDone. Fetched {fetched}, skipped {skipped} (already cached), {len(misses)} miss(es).')
    if misses:
        print("\nMisses — update wiki_2026 in data/source/councils.yaml for these:")
        for lad, name, tried in misses:
            print(f'  {lad}  {name}: tried "{tried}"')


if __name__ == '__main__':
    main()
