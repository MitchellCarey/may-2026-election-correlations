"""Unit tests for the Wikipedia wikitext parser in 30_extract_indyref.

Covers:
  - strip_wikilinks unwraps [[Page|Display]] and [[Page]] forms
  - WIKI_NAME_TO_S12 has 32 unique entries with disjoint S12 codes
  - parse_row returns None when the row-header marker is absent
  - parse_row returns ('too_few_cells'|'unparseable_votes') for malformed cells
  - parse_row extracts comma-separated vote counts as integers and
    detects Yes / No correctly regardless of the bold markup that the
    wikitable applies to the winning vote count
  - the EXPECTED_* constants match the published Electoral Commission
    headline totals so the extractor's hard-fail cross-check remains
    locked to the EC return rather than drifting with Wikipedia edits
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "indyref_extract", ROOT / "scripts" / "30_extract_indyref.py"
)
indyref_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(indyref_extract)

strip_wikilinks = indyref_extract.strip_wikilinks
parse_row = indyref_extract.parse_row
WIKI_NAME_TO_S12 = indyref_extract.WIKI_NAME_TO_S12
EXPECTED_YES_TOTAL = indyref_extract.EXPECTED_YES_TOTAL
EXPECTED_NO_TOTAL = indyref_extract.EXPECTED_NO_TOTAL
EXPECTED_YES_COUNCILS = indyref_extract.EXPECTED_YES_COUNCILS
EXPECTED_NO_COUNCILS = indyref_extract.EXPECTED_NO_COUNCILS
YEAR = indyref_extract.YEAR


# ---------------------------------------------------------------------------
# strip_wikilinks — wikilink unwrapping
# ---------------------------------------------------------------------------

def test_strip_wikilinks_pipe_form_keeps_display_text():
    assert strip_wikilinks("[[Angus, Scotland|Angus]]") == "Angus"


def test_strip_wikilinks_bare_form_keeps_page_name():
    assert strip_wikilinks("[[Aberdeen]]") == "Aberdeen"


def test_strip_wikilinks_plain_text_is_returned_unchanged():
    assert strip_wikilinks("Glasgow") == "Glasgow"


# ---------------------------------------------------------------------------
# WIKI_NAME_TO_S12 — registry invariants
# ---------------------------------------------------------------------------

def test_registry_has_32_councils():
    assert len(WIKI_NAME_TO_S12) == 32


def test_registry_codes_are_unique():
    assert len(set(WIKI_NAME_TO_S12.values())) == 32


def test_registry_codes_are_all_scottish_s12():
    assert all(code.startswith("S12") for code in WIKI_NAME_TO_S12.values())


# ---------------------------------------------------------------------------
# parse_row — well-formed rows
# ---------------------------------------------------------------------------

# A No-winning row (bold on the No cell). Matches the cached wikitext shape
# documented in scripts/30_extract_indyref.py's TABLE_START_MARKER comment.
NO_WIN_ROW = (
    '|scope="row" style="text-align:left"|Aberdeen\n'
    '| 59,390\n'
    "| '''84,094'''\n"
    '| 41.4%\n'
    "|{{No|'''58.6%'''|align=right}}\n"
    '| 143,484\n'
    '| 81.7%'
)

# A Yes-winning row (Glasgow). The wikitable's bold markup moves to the
# Yes cell when Yes wins, and the No-percent cell loses the {{No|…}}
# wrapper. Verifies parse_row doesn't depend on the {{No|…}} marker.
YES_WIN_ROW = (
    '|scope="row" style="text-align:left"|[[Glasgow]]\n'
    "|'''194,779'''\n"
    '|169,347\n'
    '|53.5%\n'
    '|46.5%\n'
    '|364,126\n'
    '|75.0%'
)


def test_parse_row_extracts_no_winner_with_comma_separated_votes():
    name, yes, no, err = parse_row(NO_WIN_ROW)
    assert err is None
    assert name == "Aberdeen"
    assert yes == 59390
    assert no == 84094


def test_parse_row_extracts_yes_winner_through_wikilink():
    name, yes, no, err = parse_row(YES_WIN_ROW)
    assert err is None
    assert name == "Glasgow"
    assert yes == 194779
    assert no == 169347


def test_parse_row_winner_picks_the_larger_count():
    """parse_row only returns raw vote counts; main() picks the winner.
    Both winning rows must yield numbers that compare correctly."""
    _, yes_no, no_no, _ = parse_row(NO_WIN_ROW)
    _, yes_y, no_y, _ = parse_row(YES_WIN_ROW)
    assert no_no > yes_no               # No-winning council
    assert yes_y > no_y                 # Yes-winning council


# ---------------------------------------------------------------------------
# parse_row — malformed rows
# ---------------------------------------------------------------------------

def test_parse_row_returns_none_when_row_header_marker_absent():
    """A row whose first cell isn't the `scope="row"` marker isn't a data
    row — parse_row should bail out rather than guess at cell positions."""
    assert parse_row("|colspan=2|footer text\n| 100\n| 200") is None


def test_parse_row_flags_too_few_cells():
    row = '|scope="row" style="text-align:left"|Aberdeen\n| 59,390'
    name, yes, no, err = parse_row(row)
    assert name == "Aberdeen"
    assert err == "too_few_cells"


def test_parse_row_flags_unparseable_votes():
    row = (
        '|scope="row" style="text-align:left"|Aberdeen\n'
        '| n/a\n'
        '| n/a'
    )
    name, yes, no, err = parse_row(row)
    assert name == "Aberdeen"
    assert err == "unparseable_votes"


# ---------------------------------------------------------------------------
# EC headline totals — locked to the Electoral Commission return
# ---------------------------------------------------------------------------

def test_ec_totals_match_published_referendum_report():
    """Sourced from the EC's Scottish-independence-referendum-report.pdf
    headline figures. If a future Wikipedia edit drifts these constants
    the extractor's cross-check will hard-fail; this test catches a
    silent edit of the constants themselves."""
    assert EXPECTED_YES_TOTAL == 1_617_989
    assert EXPECTED_NO_TOTAL == 2_001_926
    assert EXPECTED_YES_COUNCILS == 4
    assert EXPECTED_NO_COUNCILS == 28
    assert EXPECTED_YES_COUNCILS + EXPECTED_NO_COUNCILS == 32


def test_year_constant_is_2014():
    assert YEAR == 2014
