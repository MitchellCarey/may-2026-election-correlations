"""Fetch per-region wikitext from the Wikipedia "Results of the 2011 United
Kingdom Alternative Vote referendum" article and cache one JSON per
section under data/source/.

Why Wikipedia and not the Electoral Commission directly? The EC's original
per-counting-area data was hosted on the legacy `aboutmyvote.co.uk`
micro-site, which has been retired; the modern EC site's "past elections
and referendums" listing has no AV-ref-2011 entry (verified 2026-05-21
via the project's Cloudflare bypass). HoC Library RP11-44 ships analysis
as PDF only, no XLSX appendix. Wikipedia's per-region tables are the most
accessible structured source. Tier-4 in the accuracy hierarchy — we
cross-check GB headline % at extract time against the canonical 32.1% /
67.9% from RP11-44, and log per-region totals if they drift.

Outputs (one JSON per section):
  data/source/wiki_av_ref_2011_east_midlands.json        (England × 9 regions)
  data/source/wiki_av_ref_2011_east_of_england.json
  data/source/wiki_av_ref_2011_greater_london.json
  data/source/wiki_av_ref_2011_north_east_england.json
  data/source/wiki_av_ref_2011_north_west_england.json
  data/source/wiki_av_ref_2011_south_east_england.json
  data/source/wiki_av_ref_2011_south_west_england.json
  data/source/wiki_av_ref_2011_west_midlands.json
  data/source/wiki_av_ref_2011_yorkshire_and_the_humber.json
  data/source/wiki_av_ref_2011_scotland.json             (73 SPC constituencies)
  data/source/wiki_av_ref_2011_wales.json                (40 NAWC constituencies)

NI's single counting area (section 3 in the article) is intentionally not
fetched — there's no per-LAD/per-constituency breakdown to parse.

Idempotent — skips work if the per-section file already exists. Pass
--force to refetch every section. Wall-clock: ~6 s for 11 fresh fetches
with the 0.5 s courtesy interval; re-runs are instant.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
API = 'https://en.wikipedia.org/w/api.php'
PAGE = 'Results_of_the_2011_United_Kingdom_Alternative_Vote_referendum'

# (section_index, slug). Section indexes verified 2026-05-21 against the
# MediaWiki `action=parse&prop=sections` index for the page. NI's section
# (index 15) is omitted: it has no per-counting-area breakdown.
SECTIONS: tuple[tuple[int, str], ...] = (
    (6,  'east_midlands'),
    (7,  'east_of_england'),
    (8,  'greater_london'),
    (9,  'north_east_england'),
    (10, 'north_west_england'),
    (11, 'south_east_england'),
    (12, 'south_west_england'),
    (13, 'west_midlands'),
    (14, 'yorkshire_and_the_humber'),
    (16, 'scotland'),
    (17, 'wales'),
)


def cache_path(slug: str) -> Path:
    return SOURCE / f'wiki_av_ref_2011_{slug}.json'


def fetch_section(section_index: int) -> dict:
    qs = urllib.parse.urlencode({
        'action':        'parse',
        'page':          PAGE,
        'section':       str(section_index),
        'format':        'json',
        'formatversion': '2',
        'prop':          'wikitext',
        'redirects':     '1',
    })
    req = urllib.request.Request(f'{API}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true',
                    help='Refetch every section even if cached')
    args = ap.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)

    counts = {'skip': 0, 'fetch': 0, 'fail': 0}

    for section_index, slug in SECTIONS:
        out = cache_path(slug)
        if out.exists() and not args.force:
            counts['skip'] += 1
            continue
        print(f'  fetching section {section_index} → {slug}...',
              end='', flush=True)
        try:
            data = fetch_section(section_index)
        except Exception as exc:
            print(f' ERROR: {exc}', file=sys.stderr)
            counts['fail'] += 1
            continue
        if 'error' in data:
            print(f' ! {data["error"].get("code")}: '
                  f'{data["error"].get("info","")}', file=sys.stderr)
            counts['fail'] += 1
            continue
        out.write_text(json.dumps(data))
        wt_len = len(data.get('parse', {}).get('wikitext', ''))
        print(f' ok ({wt_len:,} chars)')
        counts['fetch'] += 1
        time.sleep(0.5)  # be nice to Wikipedia

    print(f'\nDone. {counts["fetch"]} fetched, {counts["skip"]} cached, '
          f'{counts["fail"]} failed (of {len(SECTIONS)} sections).')
    if counts['fail']:
        sys.exit(1)


if __name__ == '__main__':
    main()
