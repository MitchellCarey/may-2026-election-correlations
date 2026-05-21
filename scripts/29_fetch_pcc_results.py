"""Fetch the four consolidated Wikipedia articles for the Police and Crime
Commissioner elections — 2012 / 2016 / 2021 / 2024.

Wikipedia covers PCC results in **per-year consolidated articles**, not
per-(force, year) pages. The four canonical titles all follow the same
pattern (see scripts/_police_forces.py::wiki_year_title):

    2012 England and Wales police and crime commissioner elections
    2016 England and Wales police and crime commissioner elections
    2021 England and Wales police and crime commissioner elections
    2024 England and Wales police and crime commissioner elections

Each article sections each force result under a wikilink H3 heading like
``=== [[Avon and Somerset Constabulary]] ===`` followed by an
``{{Election box begin}} ... {{Election box end}}`` block carrying the
per-party vote totals and the winning-candidate template.

Idempotent: one cache file per article, ``data/source/wiki_pcc_<year>.json``.
Re-runs short-circuit on the cached files.
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from _police_forces import PCC_YEARS, wiki_year_title

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
API = 'https://en.wikipedia.org/w/api.php'


def fetch(title: str) -> dict:
    qs = urllib.parse.urlencode({
        'action':        'parse',
        'page':          title,
        'format':        'json',
        'formatversion': '2',
        'prop':          'wikitext',
        'redirects':     '1',
    })
    req = urllib.request.Request(f'{API}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    fetched = skipped = 0
    misses: list[str] = []
    for year in PCC_YEARS:
        title = wiki_year_title(year)
        out = SOURCE / f'wiki_pcc_{year}.json'
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
