"""Fetch Wikipedia results articles for the 2026 Senedd election (16
constituencies + the master article).

Counterpart to scripts/10_fetch_current_winners.py, but the Senedd doesn't
fit the per-council registry — Senedd constituencies pair Westminster
seats and don't correspond 1:1 to principal-area councils — so the list
of articles to fetch lives in this script rather than councils.yaml.

Output: one cache file per Wikipedia article,
data/source/wiki_senedd_<slug>_2026.json, idempotent (skips files that
already exist). The wiki_*.json glob in .gitignore already covers them.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from _senedd_constituencies import SENEDD_CONSTITUENCIES

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
API = 'https://en.wikipedia.org/w/api.php'

# Master article first (kept as a cross-check artefact), then the 16
# per-constituency articles from the registry.
TITLES = ["2026 Senedd election"] + [t for (_c, _n, t) in SENEDD_CONSTITUENCIES]


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
        out = SOURCE / f'wiki_senedd_{slug(title)}_2026.json'
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
