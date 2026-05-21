"""Fetch the Wikipedia article wikitext for the 18 September 2014 Scottish
independence referendum and cache it under data/source/.

The Electoral Commission is the canonical primary source for UK-wide
referendums (tier 2 in the project's accuracy hierarchy), but unlike the
2016 EU Referendum it never published a per-council CSV for indyref —
the per-counting-area numbers live only inside Appendix 3 of a PDF
report (Scottish-independence-referendum-report.pdf), with no
machine-readable companion. The Electoral Management Board for Scotland
publishes the same numbers as 32 separate sub-pages on emb.scot, one
per council, with no consolidated download.

Per the plan for issue #86, when the EC primary CSV is unavailable the
documented fallback is the Wikipedia per-council results table in the
main 2014 Scottish independence referendum article. That table is
sourced from the EC return and reproduces the official EC figures (Yes
1,617,989 / No 2,001,926; 4 Yes councils, 28 No councils) — the
extractor in scripts/30 validates against those totals so a future
silent wikitext drift surfaces as a hard failure.

Idempotent: file already at data/source/wiki_indyref_2014.json is
skipped unless --force is passed.

Issue #86. Companions:
  - 30_extract_indyref.py — wikitext → data/indyref_2014.json
  - Polygons reuse Scotland's 32 boroughs in data/ward_geoms.json (S12
    codes; the boundary set has been stable since 1996, so the WD24-era
    dissolution from scripts/09 describes the same shapes that existed
    at the 2014 vote).
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

ARTICLE_TITLE = '2014 Scottish independence referendum'
ARTICLE_URL = (
    'https://en.wikipedia.org/wiki/2014_Scottish_independence_referendum'
)
OUT_NAME = 'wiki_indyref_2014.json'

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
API = 'https://en.wikipedia.org/w/api.php'


def fetch_wikitext(title: str) -> dict:
    qs = urllib.parse.urlencode({
        'action': 'parse',
        'page': title,
        'format': 'json',
        'formatversion': '2',
        'prop': 'wikitext',
        'redirects': '1',
    })
    req = urllib.request.Request(f'{API}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true',
                    help='Re-fetch even if cache file already exists')
    args = ap.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)
    out = SOURCE / OUT_NAME

    if out.exists() and not args.force:
        print(f'Cache hit: {out.relative_to(ROOT)} (use --force to re-fetch)',
              file=sys.stderr)
        return

    print(f"Fetching '{ARTICLE_TITLE}' from {API}...", file=sys.stderr)
    payload = fetch_wikitext(ARTICLE_TITLE)
    if 'parse' not in payload or 'wikitext' not in payload.get('parse', {}):
        sys.exit(f'Unexpected payload shape from Wikipedia API: '
                 f'keys={list(payload)}')
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    wt_len = len(payload['parse']['wikitext'])
    print(f'  wrote {wt_len/1024:,.0f} KB of wikitext → '
          f'{out.relative_to(ROOT)}', file=sys.stderr)
    print(f'  source: {ARTICLE_URL}', file=sys.stderr)


if __name__ == '__main__':
    main()
