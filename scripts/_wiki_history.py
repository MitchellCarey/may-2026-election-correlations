"""Shared per-council per-year wikitext walker for the Current-page
pipeline.

Used by:
  scripts/11_extract_current.py   — collapses to newest-per-ward (existing
                                     behaviour) for data/current_winners_raw.json
  scripts/04d_build_ward_history.py — keeps every year for the time slider
                                     (issue #70 / #69 phase 1A)

Walks a council's `wiki_current_articles` registry entries newest-first,
loads each cached wikitext file (scripts/10 fetches them), dispatches the
parser keyed on electoral_system + lad_code prefix, and yields one record
per (ward, year) pair found in any article.

Caller decides whether to collapse (11) or keep all (04d). The dispatch
logic mirrors 11's existing loop so the byte-identical refactor is a
mechanical lift.
"""
import json
import re
import sys
from pathlib import Path
from typing import Iterator

from _wiki_parser import (
    parse_article,
    parse_county_article_ceds,
    parse_stv_article,
)

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "source"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def pick_parser(council: dict):
    """Return (parser_callable, is_county). Mirrors 11_extract_current.py's
    dispatch table so byte-identical output is guaranteed when 11 wires
    through this helper."""
    is_county = council["lad_code"].startswith("E10")
    system = council.get("electoral_system", "fptp")
    if is_county:
        return parse_county_article_ceds, True
    if system == "stv":
        return parse_stv_article, False
    return parse_article, False


def iter_council_year_records(council: dict) -> Iterator[tuple[int, str, dict]]:
    """Yield (year, ward_key, record) tuples for one council, newest article
    first. Records are in the shape returned by the parser:

      fptp / stv: {'prior_party': str, 'prior_year': int, ...}
      county:    {'party': str, 'year': int, 'district': str | None, ...}

    Articles with no cached file are skipped silently — the caller can scan
    `iter_missing_cache(council)` separately if it wants to report them.
    """
    articles = council.get("wiki_current_articles") or []
    if not articles:
        return
    parser, _is_county = pick_parser(council)
    name = council["name"]
    for entry in articles:
        year = entry["year"]
        path = SOURCE / f'wiki_current_{slug(name)}_{year}.json'
        if not path.exists():
            continue
        with open(path) as f:
            wt = json.load(f)['parse']['wikitext']
        parsed = parser(name, year, wt)
        for key, rec in parsed.items():
            yield year, key, rec


def iter_missing_cache(council: dict) -> Iterator[tuple[int, str]]:
    """Yield (year, expected_path) for any wiki_current_articles entry whose
    cache file is missing. Used by 11 + 04d to print a fix-it stderr line."""
    articles = council.get("wiki_current_articles") or []
    name = council["name"]
    for entry in articles:
        year = entry["year"]
        path = SOURCE / f'wiki_current_{slug(name)}_{year}.json'
        if not path.exists():
            yield year, str(path.relative_to(ROOT))
