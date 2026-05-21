"""Unit tests for the AV referendum 2011 wikitext parser in
30_extract_av_ref.

Covers:
  - parse_number handles every cell shape seen in the AV-ref wikitable:
    `{{nts|N}}` template, bold-wrapped template, dot-as-thousands typo
    (Brighton & Hove's `'''44.198'''`), plain comma-thousands, plain
    integer; returns None when no number is present.
  - parse_link extracts the article target and display name from a
    `[[…|…]]` link cell, falls back to the bare cell text when no link
    is present, and strips inline `<ref>` tags before scanning.
  - split_cells handles both the one-line (`| A || B || C`) and
    multi-line (`| A\n|B\n|C`) row grammars used in different region
    sections of the article.
  - parse_row returns a populated dict with the correct No / Yes split
    (the article's column order is name | turnout | No | Yes | … with
    No before Yes — getting this wrong flips winners across the board).
  - _normalise_name collapses ONS-style qualifiers ("Bristol, City of"
    vs "Bristol"), district / borough / council / county suffixes,
    parenthetical disambiguators, and punctuation.
  - load_overrides returns the two-tuple (name_overrides, vote_overrides)
    schema; rows without yes_votes / no_votes only contribute a name
    mapping, rows with values populate the vote-override dict.
  - resolve_code prefers explicit overrides over the registry lookup.
"""
import csv
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "av_ref_extract", ROOT / "scripts" / "30_extract_av_ref.py"
)
av_ref_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(av_ref_extract)

parse_number       = av_ref_extract.parse_number
parse_link         = av_ref_extract.parse_link
parse_row          = av_ref_extract.parse_row
split_cells        = av_ref_extract.split_cells
_normalise_name    = av_ref_extract._normalise_name
load_overrides     = av_ref_extract.load_overrides
resolve_code       = av_ref_extract.resolve_code
YEAR               = av_ref_extract.YEAR


# ---------------------------------------------------------------------------
# parse_number — every cell shape in the AV-ref tables
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cell,expected", [
    ("{{nts|29745}}",          29745),
    ("'''{{nts|22695}}'''",    22695),   # bold wrapping
    ("{{nts|12,432}}",         12432),   # comma inside template (rare but seen)
    ("'''44.198'''",           44198),   # Brighton & Hove dot-as-thousands typo
    ("9,496",                  9496),    # plain comma-thousands
    ("36605",                  36605),   # plain integer
    ("",                       None),    # empty cell
    ("(no result)",            None),    # purely textual cell
])
def test_parse_number_covers_every_cell_shape(cell, expected):
    assert parse_number(cell) == expected


def test_parse_number_prefers_template_over_dot_fallback():
    """`{{nts|...}}` must win even when the surrounding markup also has
    something that would match the dot-as-thousands fallback — order
    matters in parse_number's regex chain."""
    assert parse_number("{{nts|12345}} (36.4%)") == 12345


# ---------------------------------------------------------------------------
# parse_link — wikilink + ref-tag handling
# ---------------------------------------------------------------------------

def test_parse_link_extracts_target_and_display_from_piped_link():
    target, display = parse_link("[[Cheltenham (borough)|Cheltenham]]")
    assert target == "Cheltenham (borough)"
    assert display == "Cheltenham"


def test_parse_link_handles_bare_link_with_no_display_override():
    target, display = parse_link("[[North Devon]]")
    assert target == "North Devon"
    assert display == "North Devon"


def test_parse_link_falls_back_to_bare_cell_text_when_no_link():
    target, display = parse_link("Greater London Authority area")
    assert target == "Greater London Authority area"
    assert display == "Greater London Authority area"


def test_parse_link_strips_inline_ref_tags_before_scanning():
    target, display = parse_link("[[Bristol]]<ref>note</ref>")
    assert target == "Bristol"
    assert display == "Bristol"


# ---------------------------------------------------------------------------
# split_cells — two row grammars
# ---------------------------------------------------------------------------

def test_split_cells_one_line_grammar():
    """East Midlands / EU-ref style: `| A || B || C || D || E || F`."""
    cells = split_cells(
        "| [[Amber Valley]] || 36.42 || '''{{nts|29745}}''' "
        "|| {{nts|12432}} || '''70.50''' || 29.50"
    )
    assert len(cells) == 6
    assert "Amber Valley" in cells[0]
    assert "29745" in cells[2]
    assert "12432" in cells[3]


def test_split_cells_multi_line_grammar():
    """Scotland style: each cell on its own line, prefixed with `|`.
    The terminating `|}` must not be split as a cell."""
    cells = split_cells(
        "| [[Aberdeen Central]]\n"
        "| 43.0\n"
        "| '''{{nts|18371}}'''\n"
        "| {{nts|7342}}\n"
        "| 71.4\n"
        "| 28.6"
    )
    assert len(cells) == 6
    assert "Aberdeen Central" in cells[0]
    assert "18371" in cells[2]
    assert "7342" in cells[3]


# ---------------------------------------------------------------------------
# parse_row — column-order discipline
# ---------------------------------------------------------------------------

def test_parse_row_assigns_no_before_yes():
    """Wikipedia's per-region tables put No before Yes because No won
    nationally. Flipping the order would invert every winner."""
    row = (
        "| [[Amber Valley]] || 36.42 || '''{{nts|29745}}''' "
        "|| {{nts|12432}} || '''70.50''' || 29.50"
    )
    rec = parse_row(row)
    assert rec is not None
    assert rec["target"] == "Amber Valley"
    assert rec["display"] == "Amber Valley"
    assert rec["no_votes"] == 29745
    assert rec["yes_votes"] == 12432


def test_parse_row_rejects_rows_with_too_few_cells():
    assert parse_row("| only one cell") is None


def test_parse_row_rejects_unparseable_vote_cells():
    """A row with non-numeric vote cells is dropped — a regression here
    would silently inject None or 0 into the choropleth."""
    row = "| [[Foo]] || 40 || (no result) || (no result) || – || –"
    assert parse_row(row) is None


# ---------------------------------------------------------------------------
# _normalise_name — collapses ONS / wiki naming divergence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,normalised", [
    ("Bristol",                         "bristol"),
    ("Bristol, City of",                "bristol city of"),
    ("Cheltenham (borough)",            "cheltenham"),
    ("Cheltenham Borough",              "cheltenham"),
    ("North Dorset (district)",         "north dorset"),
    ("Metropolitan Borough of Wirral",  "wirral"),
    ("City of Westminster",             "westminster"),
    ("St. Albans",                      "st albans"),
    ("St Albans",                       "st albans"),
])
def test_normalise_name_strips_qualifiers_and_punctuation(raw, normalised):
    assert _normalise_name(raw) == normalised


# ---------------------------------------------------------------------------
# load_overrides — two-tuple schema + sparse vote-override columns
# ---------------------------------------------------------------------------

def test_load_overrides_ships_with_expected_name_and_vote_rows(tmp_path,
                                                               monkeypatch):
    """The real CSV under data/source/ ships the 6 name-only rows plus
    the 3 hand-curated vote-overrides for the Wikipedia transcription
    typos. This test exercises load_overrides directly against that
    file so a future schema change can't silently lose either group."""
    name_overrides, vote_overrides = load_overrides()
    # Name-only rows (Bristol-style ONS qualifier drift + the three
    # Scottish "Islands" vs bare-name overrides).
    assert name_overrides[("lad", "bristol")]      == "E06000023"
    assert name_overrides[("lad", "herefordshire")] == "E06000019"
    assert name_overrides[("spc", "orkney")]        == "S16000135"
    assert name_overrides[("spc", "shetland")]      == "S16000142"
    # Vote-override rows (the three SW LADs whose Wikipedia totals were
    # transcribed with values duplicated from the preceding row).
    assert vote_overrides["E07000079"] == (9462,  24367)   # Cotswold
    assert vote_overrides["E07000043"] == (10446, 23637)   # North Devon
    assert vote_overrides["E06000054"] == (45782, 113459)  # Wiltshire
    # Name-only rows must not leak into vote_overrides — a non-empty
    # vote-override row would override Wikipedia's totals.
    assert "E06000023" not in vote_overrides
    assert "S16000142" not in vote_overrides


def test_load_overrides_handles_missing_file(tmp_path, monkeypatch):
    """If the override CSV is absent the loader returns two empty dicts
    — the extractor must still run end-to-end on a clean checkout."""
    missing = tmp_path / "does_not_exist.csv"
    monkeypatch.setattr(av_ref_extract, "OVERRIDES_CSV", missing)
    name_overrides, vote_overrides = load_overrides()
    assert name_overrides == {}
    assert vote_overrides == {}


def test_load_overrides_skips_partial_vote_columns(tmp_path, monkeypatch):
    """Rows with exactly one of yes_votes / no_votes filled in must NOT
    populate vote_overrides — that would feed a half-curated number to
    ingest() and silently corrupt the per-LAD totals."""
    csv_path = tmp_path / "overrides.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["kind", "wiki_display", "code",
                         "yes_votes", "no_votes", "note"])
        writer.writerow(["lad", "PartialYes", "E07000001", "1234", "", ""])
        writer.writerow(["lad", "PartialNo",  "E07000002", "",     "5678", ""])
        writer.writerow(["lad", "FullPair",   "E07000003", "100",  "200",  ""])
    monkeypatch.setattr(av_ref_extract, "OVERRIDES_CSV", csv_path)
    _, vote_overrides = load_overrides()
    assert "E07000001" not in vote_overrides
    assert "E07000002" not in vote_overrides
    assert vote_overrides["E07000003"] == (100, 200)


# ---------------------------------------------------------------------------
# resolve_code — override → display → target fallback chain
# ---------------------------------------------------------------------------

def test_resolve_code_prefers_explicit_override():
    lookup = {"bristol city of": "E06000023"}
    overrides = {("lad", "bristol"): "E06000023"}
    assert resolve_code("lad", "Bristol", "Bristol", lookup, overrides) \
        == "E06000023"


def test_resolve_code_falls_back_to_display_name_match():
    lookup = {"amber valley": "E07000032"}
    assert resolve_code("lad", "Amber Valley", "Amber Valley",
                        lookup, {}) == "E07000032"


def test_resolve_code_falls_back_to_target_when_display_misses():
    """When the wikilink target normalises into the registry but the
    piped display label does not, resolve_code should still match via
    the target. Order: override → display → target → None."""
    lookup = {"south cambridgeshire": "E07000012"}
    # Target normalises into the lookup; display does not.
    assert resolve_code("lad", "South Cambridgeshire", "Cambs South",
                        lookup, {}) == "E07000012"


def test_resolve_code_returns_none_when_no_match():
    assert resolve_code("lad", "Unknown", "Unknown", {}, {}) is None
