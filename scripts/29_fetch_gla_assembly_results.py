"""Fetch the four per-year London Assembly election Wikipedia articles
(2012 / 2016 / 2021 / 2024) for issue #89.

Each per-year article carries both the 14 per-constituency FPTP tables
and the London-wide list seat allocation in a single page — so one fetch
per year covers every result the renderer needs. The per-constituency
articles (`Brent_and_Harrow_(London_Assembly_constituency)` etc.) carry
only free-text result lists and aren't parseable, so we deliberately
target the per-year articles instead.

Sibling of scripts/19_fetch_ge2024_results.py / scripts/14b_fetch_senedd_history.py
— same UA + courtesy-interval conventions.

Outputs (one JSON per year):
  data/source/wiki_gla_assembly_<year>.json
each carrying the raw MediaWiki `action=parse` response with the article
wikitext under `parse.wikitext`.

Idempotent — skips work if the per-year file already exists. Pass --force
to refetch everything.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gla_assembly import GLA_ASSEMBLY_YEARS

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


def cache_path(year: int) -> Path:
    return SOURCE / f'wiki_gla_assembly_{year}.json'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true', help='Refetch even if cached')
    args = ap.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)

    fetched = 0
    skipped = 0
    failed: list[tuple[int, str, str]] = []
    for year, title in GLA_ASSEMBLY_YEARS:
        path = cache_path(year)
        if path.exists() and not args.force:
            skipped += 1
            continue
        try:
            data = fetch(title)
        except Exception as exc:  # noqa: BLE001 — surface every failure
            failed.append((year, title, str(exc)))
            print(f'  ! {year} {title!r}: {exc}', file=sys.stderr)
            continue
        if 'parse' not in data or 'wikitext' not in data.get('parse', {}):
            failed.append((year, title, repr(data)[:200]))
            print(f'  ! {year} {title!r}: no parse.wikitext in response',
                  file=sys.stderr)
            continue
        path.write_text(json.dumps(data, ensure_ascii=False))
        fetched += 1
        print(f'  · {year} → {path.relative_to(ROOT)}')
        time.sleep(0.5)  # Wikipedia courtesy interval — same as 14b/17b

    print(f'\nfetched: {fetched}; skipped (cached): {skipped}; '
          f'failed: {len(failed)}')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
