"""Fetch the House of Commons Library 1918-2019 General Election results
dataset (CBP-8647) for use as the primary source for the historical
Westminster slider (issue #71 / phase 1E of #69).

Why HoC and not Wikipedia? HoC Library researchers collect per-constituency
votes **directly from Returning Officers** post-election, then cross-check
against BBC / Press Association reporting before publishing. It is the
canonical academic-grade dataset for GE 2015 / 2017 / 2019 (and earlier).
Wikipedia per-constituency Election boxes are useful as a fallback but
they are scraped — they're transcriptions of HoC/Returning Officer data
with the additional risk of editorial drift. See the project's accuracy-
hierarchy memo at the top of CLAUDE.md.

Sibling to scripts/22_fetch_surrey_results.py — the file lives behind a
Cloudflare gate on commonslibrary.parliament.uk, so we fetch it through
scripts/_official_parsers/_cloudflare.py (curl_cffi Chrome impersonation).

Two cached outputs (idempotent — files already present are skipped, --force
to rebuild):

  data/source/hoc_ge_1918_2019_by_pcon.xlsx
    Per-PCON spreadsheet keyed by ONS constituency code. Each election
    year is on its own sheet ("2015", "2017", "2019" are the ones we use);
    per-party columns inside each sheet carry Votes + Vote share for every
    party that contested the constituency. This is the primary source.

  data/source/hoc_ge_1918_2019.csv
    Normalised long-form CSV (constituency_id, election year, con/lib/lab/
    natSW/oth votes). Coarser party buckets (UKIP / Green / Brexit are
    folded into oth_votes), so 20b uses the XLSX for winner determination
    and only consults the CSV as a cross-reference. Cached anyway for
    completeness / future audit.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / '_official_parsers'))
from _cloudflare import cloudflare_session  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

# Discovered by walking the CBP-8647 briefing page on 2026-05-19 via the
# Cloudflare-bypass helper. Pinned here so 19b is a single self-contained
# fetcher that doesn't have to re-parse the briefing HTML on every run.
BRIEFING_URL = 'https://commonslibrary.parliament.uk/research-briefings/cbp-8647/'
FILES: tuple[tuple[str, str], ...] = (
    (
        'hoc_ge_1918_2019_by_pcon.xlsx',
        'https://researchbriefings.files.parliament.uk/documents/'
        'CBP-8647/1918-2019election_results_by_pcon.xlsx',
    ),
    (
        'hoc_ge_1918_2019.csv',
        'https://researchbriefings.files.parliament.uk/documents/'
        'CBP-8647/1918-2019election_results.csv',
    ),
)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true',
                    help='Re-fetch even if cache files already exist')
    args = ap.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)

    fetched = skipped = 0
    failures: list[tuple[str, str]] = []
    with cloudflare_session() as s:
        for name, url in FILES:
            out = SOURCE / name
            if out.exists() and not args.force:
                skipped += 1
                continue
            print(f'Fetching {name} from {url}...', file=sys.stderr)
            try:
                resp = s.get(url)
            except Exception as e:
                failures.append((name, repr(e)))
                continue
            if resp.status_code != 200:
                failures.append((name, f'HTTP {resp.status_code}'))
                continue
            out.write_bytes(resp.content)
            size_kb = len(resp.content) / 1024
            print(f'  wrote {size_kb:,.0f} KB → {out.relative_to(ROOT)}',
                  file=sys.stderr)
            fetched += 1

    print(f'\nDone. Fetched {fetched}, skipped {skipped} (already cached). '
          f'Source briefing: {BRIEFING_URL}', file=sys.stderr)
    if failures:
        print(f'  WARN: {len(failures)} fetch(es) failed:', file=sys.stderr)
        for name, why in failures:
            print(f'    {name}: {why}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
