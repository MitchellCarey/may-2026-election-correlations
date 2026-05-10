"""Fetch prior-election Wikipedia articles for the 10 GM boroughs.

For each ward seat up in May 2026 we want the most recent prior contest of the
same seat. The English met-borough thirds cycle elects 1/3 of seats per year for
3 years with year 4 fallow, so a 2026 seat in a thirds borough was last
contested 4 years prior, in **2022**. Salford runs all-out every 4 years; the
prior all-out was **2021**.

So we fetch:
  - 9 thirds boroughs × 2022 Wikipedia article
  - Salford × 2021 Wikipedia article

Output: data/source/wiki_<borough>_<year>.json (raw MediaWiki API response,
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

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

# (borough, year, wikipedia article title)
ARTICLES = [
    ('Bolton',     2022, '2022 Bolton Metropolitan Borough Council election'),
    ('Bury',       2022, '2022 Bury Metropolitan Borough Council election'),
    ('Manchester', 2022, '2022 Manchester City Council election'),
    ('Oldham',     2022, '2022 Oldham Metropolitan Borough Council election'),
    ('Rochdale',   2022, '2022 Rochdale Metropolitan Borough Council election'),
    ('Stockport',  2022, '2022 Stockport Metropolitan Borough Council election'),
    ('Tameside',   2022, '2022 Tameside Metropolitan Borough Council election'),
    ('Trafford',   2022, '2022 Trafford Metropolitan Borough Council election'),
    ('Wigan',      2022, '2022 Wigan Metropolitan Borough Council election'),
    ('Salford',    2021, '2021 Salford City Council election'),
]

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


SOURCE.mkdir(parents=True, exist_ok=True)
fetched = skipped = 0
for borough, year, title in ARTICLES:
    out = SOURCE / f'wiki_{borough.lower()}_{year}.json'
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
