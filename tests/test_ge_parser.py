"""Unit tests for the HoC Library XLSX parser in 20b_extract_ge_history.

Covers:
  - SPEAKER_OVERRIDES forces the (code, year) winner label + candidate
    even when the votes-max row would otherwise fold to "Other"
  - normalize_hoc_party trims inner/trailing whitespace before delegating
    to _wiki_parser.normalize_party (real HoC headers ship as "Labour ")
  - find_id_column scans row 3 (2015 layout) and row 4 (2017/2019 layout)
  - detect_party_columns skips the 'id' header so it's not misread as a
    party-group column
  - parse_sheet picks the max-votes party as the winner for non-Speaker
    rows and emits one record per ONS code prefix (E14/W07/S14/N06)
"""
import importlib.util
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "ge_extract", ROOT / "scripts" / "20b_extract_ge_history.py"
)
ge_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ge_extract)

SPEAKER_OVERRIDES = ge_extract.SPEAKER_OVERRIDES
normalize_hoc_party = ge_extract.normalize_hoc_party
find_id_column = ge_extract.find_id_column
detect_party_columns = ge_extract.detect_party_columns
parse_sheet = ge_extract.parse_sheet


# ---------------------------------------------------------------------------
# Speaker overrides
# ---------------------------------------------------------------------------

def test_speaker_overrides_cover_four_known_seats():
    """Bercow Buckingham 2010 + 2015 + 2017 and Hoyle Chorley 2019 — the only
    four GB seats where HoC folds the elected Speaker's votes into 'Other'."""
    assert SPEAKER_OVERRIDES[("E14000608", 2010)] == ("Speaker", "John Bercow")
    assert SPEAKER_OVERRIDES[("E14000608", 2015)] == ("Speaker", "John Bercow")
    assert SPEAKER_OVERRIDES[("E14000608", 2017)] == ("Speaker", "John Bercow")
    assert SPEAKER_OVERRIDES[("E14000637", 2019)] == ("Speaker", "Lindsay Hoyle")
    assert ("E14000608", 2019) not in SPEAKER_OVERRIDES
    assert ("E14000637", 2017) not in SPEAKER_OVERRIDES


# ---------------------------------------------------------------------------
# normalize_hoc_party — whitespace tolerance + delegation to _wiki_parser
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Conservative",        "Conservative"),
    ("Labour",              "Labour"),
    ("Labour ",             "Labour"),
    (" Labour",             "Labour"),
    ("Liberal Democrats",   "LibDem"),
    ("Liberal  Democrats",  "LibDem"),
    ("Scottish National",   "SNP"),
    ("Plaid Cymru",         "Plaid"),
    ("Green",               "Green"),
    ("UKIP",                "Other"),
    ("Brexit",              "Other"),
    ("DUP",                 "Other"),
    ("Sinn Féin",           "Other"),
])
def test_normalize_hoc_party_canonical_labels(raw, expected):
    assert normalize_hoc_party(raw) == expected


# ---------------------------------------------------------------------------
# Synthetic-workbook helpers — emulate the relevant rows of an HoC sheet
# ---------------------------------------------------------------------------

def _build_sheet_2015_layout():
    """2015 layout: 'id' header lives in row 3 alongside party-group headers.
    Sub-headers ('Constituency', 'Votes', 'Vote share') in row 4. Data from
    row 5 onwards."""
    wb = Workbook()
    ws = wb.active
    ws.title = "2015"
    ws["A1"] = "2015 GENERAL ELECTION"
    ws["A2"] = "Results by constituency"
    # Row 3 — party-group headers and the 'id' header
    ws["A3"] = "id"
    ws["C3"] = None
    ws["H3"] = "Conservative"
    ws["J3"] = "Liberal Democrats"
    ws["L3"] = "Labour"
    # Row 4 — sub-headers
    ws["A4"] = None
    ws["B4"] = None
    ws["C4"] = "Constituency"
    ws["H4"] = "Votes"
    ws["I4"] = "Vote share"
    ws["J4"] = "Votes"
    ws["K4"] = "Vote share"
    ws["L4"] = "Votes"
    ws["M4"] = "Vote share"
    return wb, ws


def _build_sheet_2017_layout():
    """2017/2019 layout: 'id' header lives in row 4 (under a blank cell in
    row 3), party-group headers in row 3."""
    wb = Workbook()
    ws = wb.active
    ws.title = "2017"
    ws["A1"] = "2017 GENERAL ELECTION"
    ws["A2"] = "Results by constituency"
    # Row 3 — only party-group headers
    ws["H3"] = "Conservative"
    ws["J3"] = "Liberal Democrats"
    ws["L3"] = "Labour"
    # Row 4 — sub-headers + 'id'
    ws["A4"] = "ONS id"
    ws["C4"] = "Constituency"
    ws["H4"] = "Votes"
    ws["I4"] = "Vote share"
    ws["J4"] = "Votes"
    ws["K4"] = "Vote share"
    ws["L4"] = "Votes"
    ws["M4"] = "Vote share"
    return wb, ws


def _add_row(ws, row_idx, code, name, votes_by_col):
    ws.cell(row=row_idx, column=1, value=code)
    ws.cell(row=row_idx, column=3, value=name)
    for col, n in votes_by_col.items():
        ws.cell(row=row_idx, column=col, value=n)


# ---------------------------------------------------------------------------
# find_id_column
# ---------------------------------------------------------------------------

def test_find_id_column_locates_id_in_row_3():
    _wb, ws = _build_sheet_2015_layout()
    assert find_id_column(ws) == 1  # column A


def test_find_id_column_locates_id_in_row_4():
    _wb, ws = _build_sheet_2017_layout()
    assert find_id_column(ws) == 1  # column A, in row 4


def test_find_id_column_raises_when_missing():
    wb = Workbook()
    ws = wb.active
    ws["A3"] = "Constituency"
    ws["B3"] = "Country"
    with pytest.raises(SystemExit):
        find_id_column(ws)


# ---------------------------------------------------------------------------
# detect_party_columns
# ---------------------------------------------------------------------------

def test_detect_party_columns_skips_id_header():
    _wb, ws = _build_sheet_2015_layout()
    cols = detect_party_columns(ws)
    # 'id' lives at column 1 in row 3 alongside party headers — must not
    # be picked up as a party-group.
    assert 1 not in cols
    assert cols[8] == "Conservative"
    assert cols[10] == "Liberal Democrats"
    assert cols[12] == "Labour"


# ---------------------------------------------------------------------------
# parse_sheet — end-to-end winner selection
# ---------------------------------------------------------------------------

def test_parse_sheet_picks_max_votes_winner():
    """A Labour-majority row should emit one record with w='Labour' and
    a votes dict keyed by the normalised party label."""
    _wb, ws = _build_sheet_2015_layout()
    _add_row(ws, 5, "E14000001", "TestSeat",
             {8: 5000, 10: 1000, 12: 12000})  # Con, LD, Lab
    records = parse_sheet(ws, 2015)
    assert len(records) == 1
    r = records[0]
    assert r["code"] == "E14000001"
    assert r["w"] == "Labour"
    assert r["candidate"] is None
    assert r["y"] == 2015
    assert r["src"] == "hoc"
    assert r["votes"] == {"Conservative": 5000, "LibDem": 1000, "Labour": 12000}


def test_parse_sheet_skips_footnote_rows_without_ons_prefix():
    _wb, ws = _build_sheet_2015_layout()
    _add_row(ws, 5, "E14000001", "Real",  {8: 100, 10: 50, 12: 200})
    _add_row(ws, 6, "Note: source...", "", {8: 1})
    _add_row(ws, 7, "X99000001", "Fake", {8: 1})
    records = parse_sheet(ws, 2015)
    assert [r["code"] for r in records] == ["E14000001"]


def test_parse_sheet_accepts_all_four_ons_prefixes():
    """E14 (England), W07 (Wales), S14 (Scotland), N06 (NI 2010 codes) all
    pass the prefix filter — NI rows are emitted by 20b and only get
    filtered out downstream in 07d."""
    _wb, ws = _build_sheet_2015_layout()
    _add_row(ws, 5, "E14000001", "England",  {8: 100, 12: 50})
    _add_row(ws, 6, "W07000001", "Wales",    {8: 30,  12: 200})
    _add_row(ws, 7, "S14000001", "Scotland", {8: 10,  12: 500})
    _add_row(ws, 8, "N06000001", "NI",       {8: 1,   12: 2})
    records = parse_sheet(ws, 2015)
    codes = sorted(r["code"] for r in records)
    assert codes == ["E14000001", "N06000001", "S14000001", "W07000001"]


def test_parse_sheet_speaker_override_beats_votes_max():
    """Bercow's votes appear under HoC's 'Other' column; without the
    override the winner would render as 'Other'. The override forces
    w='Speaker' and candidate='John Bercow' for (E14000608, 2015)."""
    _wb, ws = _build_sheet_2015_layout()
    # Add an "Other" column for Speaker votes — HoC's layout puts Bercow
    # outside the named party-group columns.
    ws["N3"] = "Other"
    ws["N4"] = "Votes"
    _add_row(ws, 5, "E14000608", "Buckingham",
             {8: 100, 10: 50, 12: 200, 14: 46292})  # Other wins
    records = parse_sheet(ws, 2015)
    assert len(records) == 1
    r = records[0]
    assert r["w"] == "Speaker"
    assert r["candidate"] == "John Bercow"
    # Votes dict is built from raw labels post-normalisation — Bercow's
    # 46k stays under the 'Other' bucket so the record reflects HoC's
    # source data faithfully.
    assert r["votes"]["Other"] == 46292


def test_parse_sheet_speaker_override_only_applies_to_listed_year():
    """(E14000608, 2019) is NOT in SPEAKER_OVERRIDES — Buckingham 2019
    returned a regular Conservative MP. The parser must not apply
    Bercow's override outside 2015/2017."""
    _wb, ws = _build_sheet_2017_layout()
    ws.title = "2019"
    _add_row(ws, 5, "E14000608", "Buckingham",
             {8: 37035, 10: 16624, 12: 7638})  # Con wins
    records = parse_sheet(ws, 2019)
    assert records[0]["w"] == "Conservative"
    assert records[0]["candidate"] is None
