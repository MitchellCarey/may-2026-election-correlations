"""Fetch every per-constituency + per-region Wikipedia article for the 73
Scottish Parliament constituencies in the SPC_DEC_2022 (pre-2026-review)
boundary set plus the 8 electoral regions (issue #83 extends the
constituency-only Phase 1C fetch with the d'Hondt regional-list articles).

Each per-constituency article (e.g. "Aberdeen Central (Scottish Parliament
constituency)") carries `{{Election box}}` templates for every contest since
the seat was created — so a single fetch yields both 2016 and 2021 winners
(plus 2011, 2007, ... where applicable). The downstream parser
(scripts/18b_extract_holyrood_history.py) walks those templates.

Each per-region article (e.g. "Glasgow (Scottish Parliament electoral
region)") carries `===Regional MSPs elected in YYYY===` sections with the
seven list-seat winners per year. One fetch per region yields every
contest year — same single-article-per-region pattern as constituencies,
mirroring 14b for Senedd.

Outputs (one JSON per article):
  data/source/wiki_holyrood_constituency_<SPC22CD>.json   (73 files)
  data/source/wiki_holyrood_region_<slug>.json            (8 files)
each carrying the raw MediaWiki `action=parse` response with the
article wikitext under `parse.wikitext`.

Idempotent — skips work if the per-article file already exists.
Pass --force to refetch every article.

Wall-clock: ~40 s for 81 fresh fetches (0.5 s sleep between calls;
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
from _holyrood_constituencies import HOLYROOD_22, HOLYROOD_REGIONS_22

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


def constituency_cache_path(spc22cd: str) -> Path:
    return SOURCE / f'wiki_holyrood_constituency_{spc22cd}.json'


def region_slug(name: str) -> str:
    """Convert a region display name to a filesystem-safe slug.
       "Highlands and Islands" → "highlands_and_islands"."""
    return name.lower().replace(' ', '_')


def region_cache_path(name: str) -> Path:
    return SOURCE / f'wiki_holyrood_region_{region_slug(name)}.json'


def do_fetch(label: str, key: str, wiki_title: str, out_path: Path, force: bool,
             counts: dict) -> None:
    """Shared per-article fetch + write + log handler used for both
    constituency and region passes. Increments
    counts[{'skip','fetch','fail'}] in place. Mirrors 14b.do_fetch."""
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

    for spc22cd, name, _region, wiki_title in HOLYROOD_22:
        do_fetch('constituency', spc22cd, wiki_title,
                 constituency_cache_path(spc22cd), args.force, counts)

    for region_name, wiki_title in HOLYROOD_REGIONS_22:
        do_fetch('region', region_slug(region_name), wiki_title,
                 region_cache_path(region_name), args.force, counts)

    total = len(HOLYROOD_22) + len(HOLYROOD_REGIONS_22)
    print(f'\nDone. {counts["fetch"]} fetched, {counts["skip"]} cached, '
          f'{counts["fail"]} failed (of {total} articles: '
          f'{len(HOLYROOD_22)} constituencies + '
          f'{len(HOLYROOD_REGIONS_22)} regions).')
    if counts['fail']:
        print(f'  WARN: {counts["fail"]} fetch(es) failed — patch wiki_title in '
              f'scripts/_holyrood_constituencies.py and re-run.', file=sys.stderr)


if __name__ == '__main__':
    main()
