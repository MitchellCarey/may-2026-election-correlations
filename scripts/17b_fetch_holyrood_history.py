"""Fetch every per-constituency Wikipedia article for the 73 Scottish
Parliament constituencies in the SPC_DEC_2022 (pre-2026-review) boundary set.

Each per-constituency article (e.g. "Aberdeen Central (Scottish Parliament
constituency)") carries `{{Election box}}` templates for every contest since
the seat was created — so a single fetch yields both 2016 and 2021 winners
(plus 2011, 2007, ... where applicable). The downstream parser
(scripts/18b_extract_holyrood_history.py) walks those templates.

Output: one JSON file per constituency at
  data/source/wiki_holyrood_constituency_<SPC22CD>.json
each carrying the raw MediaWiki `action=parse` response with the article
wikitext under `parse.wikitext`.

Idempotent — skips work if the per-constituency file already exists.
Pass --force to refetch every constituency.

Wall-clock: ~37 s for 73 fresh fetches (0.5 s sleep between calls;
mirrors scripts/17_fetch_holyrood_results.py's Wikipedia courtesy interval).
Re-runs are nearly instant.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _holyrood_constituencies import HOLYROOD_22

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


def cache_path(spc22cd: str) -> Path:
    return SOURCE / f'wiki_holyrood_constituency_{spc22cd}.json'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true',
                    help='Refetch every constituency even if cached')
    args = ap.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)

    n_skip = 0
    n_fetch = 0
    n_404 = 0
    for spc22cd, name, _region, wiki_title in HOLYROOD_22:
        out = cache_path(spc22cd)
        if out.exists() and not args.force:
            n_skip += 1
            continue
        print(f'  fetching {spc22cd} · {name} → {wiki_title}...', end='', flush=True)
        try:
            data = fetch(wiki_title)
        except Exception as exc:
            print(f' ERROR: {exc}', file=sys.stderr)
            n_404 += 1
            continue
        if 'error' in data:
            print(f' ! {data["error"].get("code")}: {data["error"].get("info","")}',
                  file=sys.stderr)
            n_404 += 1
            continue
        out.write_text(json.dumps(data))
        wt_len = len(data.get('parse', {}).get('wikitext', ''))
        print(f' ok ({wt_len:,} chars)')
        n_fetch += 1
        time.sleep(0.5)  # be nice to Wikipedia

    total = len(HOLYROOD_22)
    print(f'\nDone. {n_fetch} fetched, {n_skip} cached, {n_404} failed '
          f'(of {total} constituencies).')
    if n_404:
        print(f'  WARN: {n_404} fetch(es) failed — patch wiki_title in '
              f'scripts/_holyrood_constituencies.py and re-run.', file=sys.stderr)


if __name__ == '__main__':
    main()
