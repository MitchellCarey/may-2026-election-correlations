"""Unit tests for the Electoral Commission CSV parser in 26_extract_eu_ref.

Covers:
  - GB_LAD_PREFIXES gates which Area_Codes are accepted (NI / Gibraltar
    filtered, the six GB unitary/borough/council prefixes kept)
  - parse_row returns 'invalid_votes' when Leave / Remain are missing or
    not coercible to int
  - parse_row returns 'zero_votes' when Leave + Remain is 0
  - plurality winner is the side with more votes; exact ties default to
    Remain (documented tie-break)
  - the populated record carries votes + pre-computed pct (4 d.p.) so
    07d's tooltip can render "Leave 53.4% / Remain 46.6%" without
    re-floating totals at hover time
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "eu_ref_extract", ROOT / "scripts" / "26_extract_eu_ref.py"
)
eu_ref_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eu_ref_extract)

parse_row = eu_ref_extract.parse_row
GB_LAD_PREFIXES = eu_ref_extract.GB_LAD_PREFIXES
SOURCE_URL = eu_ref_extract.SOURCE_URL
YEAR = eu_ref_extract.YEAR


# ---------------------------------------------------------------------------
# GB_LAD_PREFIXES — the registry of accepted code prefixes
# ---------------------------------------------------------------------------

def test_gb_lad_prefixes_cover_only_gb_council_tiers():
    """326 + 22 + 32 = 380 GB counting areas. E06/E07/E08/E09 = English
    unitaries / districts / metro boroughs / London boroughs; W06 = Welsh
    unitaries; S12 = Scottish council areas. No N (NI) or G (Gibraltar)."""
    assert set(GB_LAD_PREFIXES) == {"E06", "E07", "E08", "E09", "W06", "S12"}


# ---------------------------------------------------------------------------
# parse_row — NI + Gibraltar filtering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,name", [
    ("N92000002", "Northern Ireland"),
    ("GI",        "Gibraltar"),
])
def test_parse_row_filters_non_gb_counting_areas(code, name):
    row = {"Area_Code": code, "Area": name, "Leave": "100", "Remain": "200"}
    out_code, out_name, record, skip = parse_row(row)
    assert out_code == code
    assert out_name == name
    assert record is None
    assert skip == "non_gb"


@pytest.mark.parametrize("code", [
    "E06000001", "E07000048", "E08000001", "E09000001",
    "W06000001", "S12000005",
])
def test_parse_row_accepts_every_gb_prefix(code):
    row = {"Area_Code": code, "Area": "TestArea", "Leave": "100", "Remain": "200"}
    _, _, record, skip = parse_row(row)
    assert skip is None
    assert record is not None


# ---------------------------------------------------------------------------
# parse_row — invalid vote handling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("votes", [
    {"Leave": "", "Remain": "200"},          # empty cell — ValueError
    {"Leave": "abc", "Remain": "200"},       # non-numeric — ValueError
    {"Leave": "100"},                        # Remain missing — KeyError
    {"Leave": None, "Remain": "200"},        # None cell — TypeError
])
def test_parse_row_rejects_unparseable_votes(votes):
    row = {"Area_Code": "E06000031", "Area": "Peterborough", **votes}
    _, _, record, skip = parse_row(row)
    assert record is None
    assert skip == "invalid_votes"


def test_parse_row_rejects_zero_vote_row():
    row = {"Area_Code": "E06000031", "Area": "Peterborough",
           "Leave": "0", "Remain": "0"}
    _, _, record, skip = parse_row(row)
    assert record is None
    assert skip == "zero_votes"


# ---------------------------------------------------------------------------
# parse_row — plurality winner + tie-break
# ---------------------------------------------------------------------------

def test_parse_row_picks_leave_when_leave_majority():
    row = {"Area_Code": "E06000031", "Area": "Peterborough",
           "Leave": "53216", "Remain": "34176"}
    _, _, record, skip = parse_row(row)
    assert skip is None
    assert record["history"][0]["w"] == "Leave"


def test_parse_row_picks_remain_when_remain_majority():
    row = {"Area_Code": "E08000003", "Area": "Manchester",
           "Leave": "108074", "Remain": "164865"}
    _, _, record, skip = parse_row(row)
    assert skip is None
    assert record["history"][0]["w"] == "Remain"


def test_parse_row_breaks_exact_tie_to_remain():
    """Defensive — EU ref had no ties in 2016, but the function must
    behave deterministically if a future referendum (#84 / #86) hits one."""
    row = {"Area_Code": "E06000001", "Area": "Synthetic",
           "Leave": "500", "Remain": "500"}
    _, _, record, skip = parse_row(row)
    assert skip is None
    assert record["history"][0]["w"] == "Remain"


# ---------------------------------------------------------------------------
# parse_row — record shape
# ---------------------------------------------------------------------------

def test_parse_row_record_carries_full_history_entry():
    """Peterborough: Leave 53216 / Remain 34176 — the EC's published
    Pct_Leave is 60.89%, which the parser must reproduce at 4 d.p.
    so the tooltip's .toFixed(1) shows '60.9% / 39.1%'."""
    row = {"Area_Code": "E06000031", "Area": "Peterborough",
           "Leave": "53216", "Remain": "34176"}
    _, _, record, _ = parse_row(row)
    assert record["name"] == "Peterborough"
    entry = record["history"][0]
    assert entry["y"] == YEAR == 2016
    assert entry["w"] == "Leave"
    assert entry["src"] == "electoral_commission"
    assert entry["url"] == SOURCE_URL
    assert entry["votes"] == {"Leave": 53216, "Remain": 34176}
    assert entry["pct"] == {"Leave": 0.6089, "Remain": 0.3911}
    # Pct must sum to 1.0 (Valid_Votes = Leave + Remain; rejected ballots
    # are excluded from the denominator).
    assert entry["pct"]["Leave"] + entry["pct"]["Remain"] == pytest.approx(1.0)
