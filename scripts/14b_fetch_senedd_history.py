"""Fetch every per-constituency Wikipedia article for the 40 pre-2026
Senedd / National Assembly for Wales constituencies (issue #69 Phase 1D / #72).

Sibling of scripts/17b_fetch_holyrood_history.py — same per-constituency
walker pattern. Each Welsh constituency article (e.g. "Aberavon (Senedd
constituency)") carries `{{AMS election box ...}}` templates for every
contest since the seat was created — so a single fetch yields the
2016 + 2021 winners (plus 2011, 2007, 2003, 1999 where applicable).
The downstream parser (scripts/15b_extract_senedd_history.py) walks
those templates.

Welsh constituencies use the same AMS template family as Holyrood
(Wales also runs Additional Member System: FPTP constituency vote +
regional list vote on the same ballot) — only the tail `hold/gain`
template differs (Welsh form uses `{{Election box hold|gain with
party link}}` instead of `{{AMS election box win|hold|gain}}`).

Output: one JSON file per constituency at
  data/source/wiki_senedd_constituency_<NAWC21CD>.json
each carrying the raw MediaWiki `action=parse` response with the article
wikitext under `parse.wikitext`.

Idempotent — skips work if the per-constituency file already exists.
Pass --force to refetch every constituency.

Wall-clock: ~20 s for 40 fresh fetches (0.5 s sleep between calls;
mirrors 17b's Wikipedia courtesy interval). Re-runs are nearly instant.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _senedd_constituencies_2007 import SENEDD_CONSTITUENCIES_2007

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


def cache_path(nawc21cd: str) -> Path:
    return SOURCE / f'wiki_senedd_constituency_{nawc21cd}.json'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true',
                    help='Refetch every constituency even if cached')
    args = ap.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)

    n_skip = 0
    n_fetch = 0
    n_404 = 0
    for nawc21cd, name, wiki_title, _region in SENEDD_CONSTITUENCIES_2007:
        out = cache_path(nawc21cd)
        if out.exists() and not args.force:
            n_skip += 1
            continue
        print(f'  fetching {nawc21cd} · {name} → {wiki_title}...', end='', flush=True)
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

    total = len(SENEDD_CONSTITUENCIES_2007)
    print(f'\nDone. {n_fetch} fetched, {n_skip} cached, {n_404} failed '
          f'(of {total} constituencies).')
    if n_404:
        print(f'  WARN: {n_404} fetch(es) failed — patch wiki_title in '
              f'scripts/_senedd_constituencies_2007.py and re-run.', file=sys.stderr)


if __name__ == '__main__':
    main()
