"""Fetch prior-election Wikipedia articles for every council in the registry.

For each ward seat up in May 2026 we want the most recent prior contest of the
same seat. The English met-borough thirds cycle elects 1/3 of seats per year
for 3 years with year 4 fallow, so a 2026 seat in a thirds borough was last
contested 4 years prior (2022). Salford runs all-out every 4 years; the prior
all-out was 2021. Welsh and Scottish councils run all-out on a 5-year cycle;
the prior all-out was 2022 for both.

The registry data/source/councils.yaml specifies wiki_prior + wiki_prior_year
per row. We fetch one Wikipedia article per row that has a wiki_prior value;
rows with wiki_prior: null are skipped.

Output: data/source/wiki_<council>_<year>.json (raw MediaWiki API response
containing the article wikitext). Idempotent — skips files that already exist.

Originally planned to use the House of Commons Library annual XLSX handbooks,
but commonslibrary.parliament.uk sits behind a Cloudflare managed challenge
that blocks programmatic clients. Wikipedia is more accessible and the per-ward
"hold" / "gain from X" templates are straightforward to parse downstream.
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from _councils import for_region

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
API = 'https://en.wikipedia.org/w/api.php'


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
    for council in for_region("gb"):
        if not council.get("wiki_prior"):
            continue
        year = council["wiki_prior_year"]
        title = council["wiki_prior"]
        out = SOURCE / f'wiki_{council["name"].lower()}_{year}.json'
        if out.exists():
            skipped += 1
            continue
        print(f'Fetching {title}...')
        data = fetch(title)
        if 'error' in data:
            raise RuntimeError(f'{title}: {data["error"]}')
        with open(out, 'w') as f:
            json.dump(data, f)
        fetched += 1
        time.sleep(0.5)  # be nice to Wikipedia

    print(f'\nDone. Fetched {fetched}, skipped {skipped} (already cached).')


if __name__ == '__main__':
    main()
