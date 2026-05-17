"""Dispatch official-source results from cached fetches into the per-year CSVs.

Counterpart to scripts/11_extract_current.py. For each council in
data/source/councils.yaml that declares an `official_url` + `official_parser`,
13 reads the cached fetch (produced by scripts/12_fetch_official_results.py),
dispatches to the matching module in scripts/_official_parsers/, and writes
the parsed rows into:

    data/source/county_official_<year>.csv  — for E10 (county) councils
    data/source/ward_official_<year>.csv    — for every other council

CSV schemas:

    county_official_<year>.csv:
        lad_code, county, division, party, candidate, votes, source
    ward_official_<year>.csv:
        lad_code, council, ward, party, candidate, votes, source

Hand-curated rows already in either CSV are preserved by `(lad_code,
normalised_ward)` key. Parser-emitted rows replace any existing row whose
(lad_code, ward) matches after normalisation; existing rows whose ward the
parser did NOT emit survive. This lets a council with a registered parser
also carry hand-curated supplements for the specific wards the parser
misses (Wikipedia + official source both silent — see #64 approach (2)).

For a council with no `official_parser` registered, the dedup-by-key has
no replaced_keys entries for that lad, so every existing row survives —
preserving the Phase 1 hand-curated pattern (e.g. Norfolk before its
parser landed).

Until Phase 2 lands the first parser, this is a no-op: zero councils have
`official_url` set, so nothing is parsed and the CSVs are not touched.
"""
import csv
import importlib
import re
from pathlib import Path

from _councils import for_region

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"

COUNTY_FIELDS = ['lad_code', 'county', 'division', 'party', 'candidate', 'votes', 'source']
WARD_FIELDS   = ['lad_code', 'council', 'ward',     'party', 'candidate', 'votes', 'source']


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _norm_ward(s: str) -> str:
    """Loose ward-name match for dedup. Lowercase, ' and ' → ' & ' (parsers
    inconsistently use one or the other — moderngov gives 'and', Bradford's
    bespoke parser gives '&', curators type whichever), collapse whitespace.
    Keeps the dedup key tight enough that a re-extracted parser run still
    overrides its own prior rows, but loose enough that 'Astley Bridge' from
    a hand-curated row dedupes against 'Astley  Bridge' from the parser."""
    return ' '.join(s.lower().replace(' and ', ' & ').split())


def main():
    # Group new rows by (year, scope) so each output file is written once.
    by_target: dict[tuple[int, str], list[dict]] = {}
    by_target_lads: dict[tuple[int, str], set[str]] = {}
    missing_cache: list[tuple[str, int]] = []
    errors = 0

    for council in for_region("gb"):
        url = council.get("official_url")
        if not url:
            continue
        parser_key = council.get("official_parser")
        year = council.get("official_year")
        if not parser_key or not year:
            print(f'  ! {council["name"]}: official_url set but '
                  f'official_parser or official_year missing — skipping')
            errors += 1
            continue
        try:
            mod = importlib.import_module(f'_official_parsers.{parser_key}')
        except ModuleNotFoundError:
            print(f'  ! {council["name"]}: parser "{parser_key}" not found '
                  f'in scripts/_official_parsers/ — skipping')
            errors += 1
            continue
        ext = getattr(mod, 'extension', 'html')
        cache = SOURCE / f'official_{slug(council["name"])}_{year}.{ext}'
        if not cache.exists():
            missing_cache.append((council["name"], year))
            continue
        rows = mod.parse(cache.read_bytes(), council=council, year=year)
        scope = 'county' if council["lad_code"].startswith("E10") else 'ward'
        key = (year, scope)
        by_target.setdefault(key, []).extend(rows)
        by_target_lads.setdefault(key, set()).add(council["lad_code"])

    if not by_target:
        print("No parsed rows. (No councils with official_url + parser, or all "
              "cached fetches missing.) Nothing written.")
        if missing_cache:
            print(f'  ({len(missing_cache)} council/year pair(s) missing cached '
                  f'fetch; run scripts/12_fetch_official_results.py first.)')
        return

    for (year, scope), new_rows in by_target.items():
        path = SOURCE / f'{scope}_official_{year}.csv'
        fields = COUNTY_FIELDS if scope == 'county' else WARD_FIELDS
        name_field = 'division' if scope == 'county' else 'ward'
        # Replace existing rows by (lad_code, normalised ward/division) rather
        # than by lad_code alone. A council with a registered parser can still
        # carry hand-curated supplements for wards the parser doesn't emit
        # (e.g. Wikipedia + ModernGov both silent on a single ward) — those
        # rows survive across re-extracts because they don't share a
        # normalised key with anything the parser produced this run.
        replaced_keys = {(r['lad_code'], _norm_ward(r[name_field])) for r in new_rows}
        existing_kept: list[dict] = []
        if path.exists():
            with open(path, newline='') as f:
                for r in csv.DictReader(f):
                    if (r['lad_code'], _norm_ward(r[name_field])) not in replaced_keys:
                        existing_kept.append(r)
        with open(path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in existing_kept:
                w.writerow({k: r.get(k, '') for k in fields})
            for r in new_rows:
                w.writerow({k: r.get(k, '') for k in fields})
        replaced_lads = by_target_lads[(year, scope)]
        print(f'Wrote {path.name} — {len(existing_kept)} kept + {len(new_rows)} new '
              f'= {len(existing_kept) + len(new_rows)} rows '
              f'({len(replaced_lads)} council(s) re-extracted)')

    if missing_cache:
        print(f'\n{len(missing_cache)} council/year pair(s) had no cached fetch — '
              f'run scripts/12_fetch_official_results.py:')
        for name, year in missing_cache:
            print(f'  {name} {year}')
    if errors:
        print(f'\n{errors} error(s); see warnings above.')


if __name__ == '__main__':
    main()
