"""Fetch raw official-source results pages for every council that declares
an `official_url` in data/source/councils.yaml.

Counterpart to scripts/10_fetch_current_winners.py — where 10 fetches
Wikipedia, 12 fetches the council's own results page from
elections.<council>.gov.uk or equivalent. Each council declares its source
URL and the parser key (handled by scripts/13_extract_official.py); 12's
job is just to retrieve and cache.

Output: data/source/official_<slug>_<year>.<ext>. Idempotent — skips files
that already exist. Extension is determined by the parser module's
`extension` attribute (e.g. 'html', 'json', 'pdf'); the dispatcher imports
the parser module lazily so that adding a new pattern doesn't require
editing this script.

Phase 1 (Norfolk) ships hand-curated CSV data directly in
data/source/county_official_2026.csv with no entry here. Once Norfolk
acquires an `official_url` + parser, 12 will start fetching it.

Until Phase 2 lands parsers, this is a no-op: zero councils have
`official_url` set, so the loop body never runs.
"""
import importlib
import re
import time
import urllib.request
from pathlib import Path

from _councils import for_region

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def default_fetch(url: str) -> bytes:
    """Plain GET. Parser modules may export their own fetch() to override
    (e.g. Power BI dashboards need a POST with a querydata payload)."""
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    fetched = skipped = errors = 0
    registered = 0
    for council in for_region("gb"):
        url = council.get("official_url")
        if not url:
            continue
        registered += 1
        parser_key = council.get("official_parser")
        year = council.get("official_year")
        if not parser_key or not year:
            print(f'  ! {council["name"]}: official_url set but official_parser '
                  f'or official_year missing — skipping')
            errors += 1
            continue
        # Parser module may override fetch() and declare its own extension.
        try:
            mod = importlib.import_module(f'_official_parsers.{parser_key}')
        except ModuleNotFoundError:
            print(f'  ! {council["name"]}: parser "{parser_key}" not found in '
                  f'scripts/_official_parsers/ — skipping')
            errors += 1
            continue
        ext = getattr(mod, 'extension', 'html')
        fetch = getattr(mod, 'fetch', default_fetch)
        out = SOURCE / f'official_{slug(council["name"])}_{year}.{ext}'
        if out.exists():
            skipped += 1
            continue
        print(f'Fetching {council["name"]} {year} via {parser_key}...')
        try:
            content = fetch(url) if fetch is default_fetch else fetch(url, council=council, year=year)
        except Exception as e:
            print(f'  ! {council["name"]}: fetch failed — {e!r}')
            errors += 1
            time.sleep(0.5)
            continue
        out.write_bytes(content)
        fetched += 1
        time.sleep(0.5)  # be nice to council websites

    print(f'\nDone. {registered} council(s) with official_url; '
          f'fetched {fetched}, skipped {skipped} (already cached), '
          f'{errors} error(s).')


if __name__ == '__main__':
    main()
