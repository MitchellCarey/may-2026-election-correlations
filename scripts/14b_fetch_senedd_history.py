"""Fetch every per-constituency + per-region Wikipedia article for the 40
pre-2026 Senedd / National Assembly for Wales constituencies plus the
5 electoral regions (issue #69 Phase 1D / #72).

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

Each per-region article (e.g. "North Wales (Senedd electoral region)")
carries `===Regional MSs/AMs elected in YYYY===` sections with the four
list-seat winners per year. One fetch per region yields every contest
year — same single-article-per-region pattern as constituencies.

Outputs (one JSON per article):
  data/source/wiki_senedd_constituency_<NAWC21CD>.json   (40 files)
  data/source/wiki_senedd_region_<slug>.json             (5 files)
each carrying the raw MediaWiki `action=parse` response with the
article wikitext under `parse.wikitext`.

Idempotent — skips work if the per-article file already exists.
Pass --force to refetch everything.

Wall-clock: ~22 s for 45 fresh fetches (0.5 s sleep between calls;
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
from _senedd_constituencies_2007 import SENEDD_CONSTITUENCIES_2007, SENEDD_REGIONS_2007

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


def constituency_cache_path(nawc21cd: str) -> Path:
    return SOURCE / f'wiki_senedd_constituency_{nawc21cd}.json'


def region_slug(name: str) -> str:
    """Convert a region display name to a filesystem-safe slug.
       "South Wales West" → "south_wales_west"."""
    return name.lower().replace(' ', '_')


def region_cache_path(name: str) -> Path:
    return SOURCE / f'wiki_senedd_region_{region_slug(name)}.json'


def do_fetch(label: str, key: str, wiki_title: str, out_path: Path, force: bool,
             counts: dict) -> None:
    """Shared per-article fetch + write + log handler used for both constituency
    and region passes. Increments counts[{'skip','fetch','fail'}] in place."""
    if out_path.exists() and not force:
        counts['skip'] += 1
        return
    print(f'  fetching {label} {key} → {wiki_title}...', end='', flush=True)
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

    for nawc21cd, name, wiki_title, _region in SENEDD_CONSTITUENCIES_2007:
        do_fetch('constituency', nawc21cd, wiki_title,
                 constituency_cache_path(nawc21cd), args.force, counts)

    for region_name, wiki_title in SENEDD_REGIONS_2007:
        do_fetch('region', region_slug(region_name), wiki_title,
                 region_cache_path(region_name), args.force, counts)

    total = len(SENEDD_CONSTITUENCIES_2007) + len(SENEDD_REGIONS_2007)
    print(f'\nDone. {counts["fetch"]} fetched, {counts["skip"]} cached, '
          f'{counts["fail"]} failed (of {total} articles: '
          f'{len(SENEDD_CONSTITUENCIES_2007)} constituencies + '
          f'{len(SENEDD_REGIONS_2007)} regions).')
    if counts['fail']:
        print(f'  WARN: {counts["fail"]} fetch(es) failed — patch wiki_title in '
              f'scripts/_senedd_constituencies_2007.py and re-run.', file=sys.stderr)


if __name__ == '__main__':
    main()
