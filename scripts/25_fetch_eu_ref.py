"""Fetch the Electoral Commission per-counting-area CSV for the 23 June
2016 EU referendum and cache it under data/source/.

The Electoral Commission is the canonical primary source for UK-wide
referendum and electoral results — tier 2 in the project's accuracy
hierarchy (see CLAUDE.md "Data accuracy is paramount"). The CSV was
published by the EC on 2016-06-24 and republished in its current form on
2019-07-26; the URL and file shape have been stable since.

The full HTML results page on electoralcommission.org.uk sits behind a
Cloudflare managed challenge, but the CSV download itself is served as a
static asset through Cloudflare's CDN (cf-cache-status: HIT) — a plain
GET with a real-browser User-Agent works without the Chrome-impersonation
bypass that scripts/19b uses for the HoC Library. If the EC ever changes
this and the script starts 403'ing, swap urllib for
scripts/_official_parsers/_cloudflare.cloudflare_session(), same recipe
as 19b.

Idempotent: file already at data/source/ec_eu_referendum_2016.csv is
skipped unless --force is passed.

Bootstrapped by issue #85 (EU Ref 2016 LAD-level overlay). Companions:
  - 26_extract_eu_ref.py  — CSV → data/eu_ref_2016.json
  - 27_fetch_lad_2016_geoms.py — 2016-vintage LAD polygons
"""
import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

# Discovered 2026-05-20 by probing the EC site with a real-browser UA.
# The CSV ETag has been stable since 2019-07-26; pinning the URL means
# this fetcher is a single self-contained script that doesn't have to
# re-parse the results page.
RESULTS_PAGE = (
    'https://www.electoralcommission.org.uk/'
    'who-we-are-and-what-we-do/elections-and-referendums/'
    'past-elections-and-referendums/eu-referendum/'
    'results-and-turnout-eu-referendum'
)
FILES: tuple[tuple[str, str], ...] = (
    (
        'ec_eu_referendum_2016.csv',
        'https://www.electoralcommission.org.uk/sites/default/files/'
        '2019-07/EU-referendum-result-data.csv',
    ),
)

# A modern Chrome UA — the EC CDN serves the CSV with a permissive cache
# policy under a real-browser UA but 403s plain `python-urllib` / curl
# defaults. The bytes returned are identical across UAs once accepted.
UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/130.0.0.0 Safari/537.36'
)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true',
                    help='Re-fetch even if cache files already exist')
    args = ap.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)

    fetched = skipped = 0
    failures: list[tuple[str, str]] = []
    for name, url in FILES:
        out = SOURCE / name
        if out.exists() and not args.force:
            skipped += 1
            continue
        print(f'Fetching {name} from {url}...', file=sys.stderr)
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
        except Exception as e:
            failures.append((name, repr(e)))
            continue
        out.write_bytes(data)
        size_kb = len(data) / 1024
        print(f'  wrote {size_kb:,.0f} KB → {out.relative_to(ROOT)}',
              file=sys.stderr)
        fetched += 1

    print(f'\nDone. Fetched {fetched}, skipped {skipped} (already cached). '
          f'Source page: {RESULTS_PAGE}', file=sys.stderr)
    if failures:
        print(f'  WARN: {len(failures)} fetch(es) failed:', file=sys.stderr)
        for name, why in failures:
            print(f'    {name}: {why}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
