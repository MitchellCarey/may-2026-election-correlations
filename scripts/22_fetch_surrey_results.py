"""Fetch Wikipedia results articles for the two 2026 Surrey unitary
elections (East Surrey, West Surrey).

Counterpart to scripts/14_fetch_senedd_results.py — the Surrey unitaries
don't have ONS LAD codes (administrative effect 1 April 2027) and so
don't fit the per-council registry in councils.yaml. The list of articles
to fetch lives in scripts/_surrey_unitaries.py.

Output: one cache file per article,
data/source/wiki_surrey_<slug>_2026.json, idempotent (skips files that
already exist). The wiki_*.json glob in .gitignore already covers them.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from _surrey_unitaries import SURREY_UNITARIES

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
API = 'https://en.wikipedia.org/w/api.php'

TITLES = [t for (_c, _n, t, _d) in SURREY_UNITARIES]


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
    for title in TITLES:
        out = SOURCE / f'wiki_surrey_{slug(title)}_2026.json'
        if out.exists():
            skipped += 1
            continue
        print(f'Fetching {title}...')
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
