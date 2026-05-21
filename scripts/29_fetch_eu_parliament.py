"""Fetch the 11 per-constituency Wikipedia articles for the European
Parliament EERs (issue #91). Each article carries the per-year results
for every contest the constituency ever held; the 2014 + 2019 sections
are what the downstream parser (scripts/30_extract_eu_parliament.py)
consumes.

Sibling to scripts/14b_fetch_senedd_history.py and scripts/17b_fetch_
holyrood_history.py — same one-fetch-per-constituency pattern with
brace-delimited per-year `{{Election box begin for list|title=[[YYYY
European Parliament election ...]]: <Region>}}` blocks inside an
`== Election results ==` H2.

Outputs (one JSON per article):
  data/source/wiki_ep_<eer_code>.json
each carrying the raw MediaWiki `action=parse` response with the article
wikitext under `parse.wikitext`.

Idempotent — skips work if the per-article file already exists.
Pass --force to refetch every article.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _eu_parliament import EU_PARLIAMENT_REGIONS

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
API = 'https://en.wikipedia.org/w/api.php'


def fetch(title: str) -> dict:
    qs = urllib.parse.urlencode({
        'action':         'parse',
        'page':           title,
        'format':         'json',
        'formatversion':  '2',
        'prop':           'wikitext',
        'redirects':      '1',
    })
    req = urllib.request.Request(f'{API}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def cache_path(eer_code: str) -> Path:
    return SOURCE / f'wiki_ep_{eer_code}.json'


def do_fetch(eer_code: str, name: str, wiki_title: str,
             force: bool, counts: dict) -> None:
    out_path = cache_path(eer_code)
    if out_path.exists() and not force:
        counts['skip'] += 1
        return
    print(f'  fetching {eer_code} {name} → {wiki_title}...',
          end='', flush=True)
    try:
        data = fetch(wiki_title)
    except Exception as exc:
        print(f' ERROR: {exc}', file=sys.stderr)
        counts['fail'] += 1
        return
    if 'error' in data:
        print(f' ! {data["error"].get("code")}: {data["error"].get("info","")}',
              file=sys.stderr)
        counts['fail'] += 1
        return
    out_path.write_text(json.dumps(data))
    wt_len = len(data.get('parse', {}).get('wikitext', ''))
    print(f' ok ({wt_len:,} chars)')
    counts['fetch'] += 1
    time.sleep(0.5)  # be nice to Wikipedia


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true',
                    help='Refetch every article even if cached')
    args = ap.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)
    counts = {'skip': 0, 'fetch': 0, 'fail': 0}

    for eer_code, name, wiki_title in EU_PARLIAMENT_REGIONS:
        do_fetch(eer_code, name, wiki_title, args.force, counts)

    total = len(EU_PARLIAMENT_REGIONS)
    print(f'\nDone. {counts["fetch"]} fetched, {counts["skip"]} cached, '
          f'{counts["fail"]} failed (of {total} articles).')
    if counts['fail']:
        print(f'  WARN: {counts["fail"]} fetch(es) failed — patch wiki_title '
              f'in scripts/_eu_parliament.py and re-run.', file=sys.stderr)


if __name__ == '__main__':
    main()
