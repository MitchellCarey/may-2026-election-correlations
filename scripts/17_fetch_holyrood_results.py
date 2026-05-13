"""Fetch the Wikipedia results article for the 2026 Scottish Parliament election.

All 73 FPTP constituency winners are tabulated together in a single article
("Results of the 2026 Scottish Parliament election"), so this is a one-shot
fetch — much simpler than the per-council Wikipedia walk in scripts/10.

Output: data/source/wiki_holyrood_2026.json — the raw MediaWiki `action=parse`
response, with the article wikitext under `parse.wikitext`. The downstream
parser (scripts/18_extract_holyrood.py) walks the wikitable to extract the
winner per constituency.

Idempotent — skips work if the output already exists. Pass --force to refetch.
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"
OUT = SOURCE / "wiki_holyrood_2026.json"

ARTICLE_TITLE = "Results of the 2026 Scottish Parliament election"
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
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true', help='Refetch even if the file is cached')
    args = ap.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)
    if OUT.exists() and not args.force:
        print(f'{OUT.relative_to(ROOT)} already cached — skipping. Use --force to refetch.')
        return

    print(f'Fetching {ARTICLE_TITLE}...')
    data = fetch(ARTICLE_TITLE)
    if 'error' in data:
        raise SystemExit(f'  ! {data["error"].get("code")}: {data["error"].get("info", "")}')
    OUT.write_text(json.dumps(data))
    wt_len = len(data.get('parse', {}).get('wikitext', ''))
    print(f'Cached → {OUT.relative_to(ROOT)} (wikitext {wt_len:,} chars)')
    time.sleep(0.5)  # be nice to Wikipedia


if __name__ == '__main__':
    main()
