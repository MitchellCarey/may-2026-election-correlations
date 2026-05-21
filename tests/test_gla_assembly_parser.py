"""Unit tests for the per-year London Assembly article parser in
30_extract_gla_assembly.

Covers:
  - WINNER_CELL_RE / parse_fptp_winner: bg-coloured bold cell is what
    identifies the winner across 2012-2024; losing rows have neither
    the colour nor the bold marker, so the wrong row never wins.
  - COLOUR_TO_PARTY: the four observed colour codes (`faa`/`ffaaaa` Lab,
    `aacfff` Con, `ffd152` LibDem) map to the right party.
  - _strip_winner_name: resolves bare and disambiguated wikilinks,
    drops `{{efn|...}}` annotations and trailing `(I)` incumbency
    markers, decodes `&nbsp;` from the 2012 article's display labels.
  - find_constituency_row: anchors on the `(London Assembly constituency)`
    link and stops at the next `|-` / `|}` so a downstream row isn't
    pulled in.
  - parse_list_seats_election_results: pulls `partyN` + `seatsN_2` pairs
    from the `{{Election results}}` template (2016 / 2021 / 2024 form),
    skips zero-seat rows, keeps both normalised + raw labels.
  - parse_list_seats_ams_summary: pulls `party` + `AMS seats` from the
    2012 `{{AMS Election Summary Party}}` per-party templates and copes
    with nested `{{increase}}` markers inside the block body.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 30's filename starts with a digit so a plain `import` won't work — load
# it by spec the same way the sibling parser tests do.
_spec = importlib.util.spec_from_file_location(
    "gla_assembly_extract", ROOT / "scripts" / "30_extract_gla_assembly.py"
)
gla_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gla_extract)

_strip_winner_name = gla_extract._strip_winner_name
find_constituency_row = gla_extract.find_constituency_row
parse_fptp_winner = gla_extract.parse_fptp_winner
parse_list_seats_election_results = gla_extract.parse_list_seats_election_results
parse_list_seats_ams_summary = gla_extract.parse_list_seats_ams_summary
extract_template_body = gla_extract.extract_template_body
COLOUR_TO_PARTY = gla_extract.COLOUR_TO_PARTY
ELECTION_RESULTS_OPEN_RE = gla_extract.ELECTION_RESULTS_OPEN_RE


# ---------------------------------------------------------------------------
# _strip_winner_name — wikilink + annotation cleanup
# ---------------------------------------------------------------------------

def test_strip_winner_name_resolves_disambiguated_wikilink():
    """`[[Page (Disambig)|Display]]` must collapse to `Display` so the
    candidate field renders the human-readable name, not the wiki path."""
    assert _strip_winner_name(
        "[[Gareth Roberts (politician)|Gareth Roberts]]"
    ) == "Gareth Roberts"


def test_strip_winner_name_resolves_bare_wikilink():
    """`[[Page]]` with no piped display must use the page title verbatim."""
    assert _strip_winner_name("[[Anne Clarke]]") == "Anne Clarke"


def test_strip_winner_name_drops_efn_footnote_annotation():
    """The 2024 South West cell wraps the candidate in
    `'''[[…|Gareth Roberts]]'''{{efn|name=London-wide}}`; the `{{efn}}`
    sits inside the bold body and must be stripped from the captured
    display name."""
    assert _strip_winner_name(
        "[[Gareth Roberts (politician)|Gareth Roberts]]{{efn|name=London-wide}}"
    ) == "Gareth Roberts"


def test_strip_winner_name_decodes_nbsp_entity():
    """2012's article uses literal `&nbsp;` between forename and surname
    inside the wikilink display — the resolver must turn that back into
    a regular space so the candidate string doesn't carry the entity."""
    assert _strip_winner_name(
        "[[Andrew Dismore|Andrew&nbsp;Dismore]]"
    ) == "Andrew Dismore"


def test_strip_winner_name_drops_trailing_incumbency_marker():
    """Older articles append `(I)` after a wikilink to mark incumbents.
    The marker belongs in metadata, not in the candidate's display name."""
    assert _strip_winner_name("[[Joanne McCartney]] (I)") == "Joanne McCartney"


def test_strip_winner_name_passes_plain_text_through():
    """No wikilink, no annotation — the body is already a clean name."""
    assert _strip_winner_name("Marina Ahmad") == "Marina Ahmad"


# ---------------------------------------------------------------------------
# WINNER_CELL_RE / parse_fptp_winner — bg-coloured bold cell detection
# ---------------------------------------------------------------------------

# Realistic shape for a 2024 South West row — the LibDem winner has the
# `#ffd152` background AND the bold marker; losers have neither.
SOUTH_WEST_2024_ROW = """\
| [[South West (London Assembly constituency)|South West]]
| Marcela Benedetti<br />(50,656, 2nd)
| Ron Mushiso{{efn|name=candidate}}<br />(49,981, 3rd)
| Chas Warlow<br />(17,696, 4th)
| style="background:#ffd152;" | '''[[Gareth Roberts (politician)|Gareth Roberts]]'''{{efn|name=London-wide}}<br />(66,675, 1st)
| Steve Chilcott{{efn|name=London-wide}}<br />(14,450, 5th)
"""


def test_parse_fptp_winner_picks_bg_coloured_bold_cell_over_losers():
    """South West 2024: the Labour candidate is 2nd at 50,656 votes but
    has no `style="background:…"` and no `'''…'''`; the LibDem winner has
    both. A regex that picked the wrong row by votes or by row order
    would silently mis-attribute the constituency."""
    party, candidate = parse_fptp_winner(SOUTH_WEST_2024_ROW)
    assert party == "LibDem"
    assert candidate == "Gareth Roberts"


def test_parse_fptp_winner_returns_none_when_no_bold_bg_cell():
    """A row with no winner candidate (e.g. partial article during
    declaration) should produce `None`, not raise."""
    row = (
        "| [[Brent and Harrow (London Assembly constituency)|Brent and Harrow]]\n"
        "| Alice<br />(100, 1st)\n"
        "| Bob<br />(50, 2nd)\n"
    )
    assert parse_fptp_winner(row) is None


def test_parse_fptp_winner_handles_short_three_char_hex_form():
    """Wikipedia editors mix `#faa` and `#ffaaaa` for Labour. The regex
    accepts both 3- and 6-char hex codes; dropping the short form would
    miss every constituency that uses the abbreviated red."""
    row = (
        "| [[Some (London Assembly constituency)|Some]]\n"
        "| style=\"background:#faa;\" | '''[[Joe Bloggs]]'''\n"
    )
    party, candidate = parse_fptp_winner(row)
    assert party == "Labour"
    assert candidate == "Joe Bloggs"


def test_colour_to_party_covers_observed_2012_2024_palette():
    """The four hex codes actually present in the 2012-2024 articles —
    losing any of these would silently drop a constituency winner."""
    assert COLOUR_TO_PARTY["faa"] == "Labour"
    assert COLOUR_TO_PARTY["ffaaaa"] == "Labour"
    assert COLOUR_TO_PARTY["aacfff"] == "Conservative"
    assert COLOUR_TO_PARTY["ffd152"] == "LibDem"


# ---------------------------------------------------------------------------
# find_constituency_row — row extraction stops at the next row separator
# ---------------------------------------------------------------------------

TWO_ROW_TABLE = """\
| [[Barnet and Camden (London Assembly constituency)|Barnet & Camden]]
| Alice<br />(10, 2nd)
| style="background:#ffaaaa;" | '''[[Anne Clarke]]'''
|-
| [[Bexley and Bromley (London Assembly constituency)|Bexley & Bromley]]
| Bob<br />(20, 2nd)
| style="background:#aacfff;" | '''[[Thomas Turrell]]'''
|}
"""


def test_find_constituency_row_returns_only_the_named_constituency():
    """Without a `\\n|-` / `\\n|}` stop, the slice would swallow the next
    constituency's bold cell and mis-attribute the winner. The two-row
    fixture proves the boundary holds."""
    row = find_constituency_row(TWO_ROW_TABLE, "Barnet and Camden")
    assert row is not None
    assert "Anne Clarke" in row
    assert "Thomas Turrell" not in row, (
        "Barnet's row must NOT spill into Bexley's row; the `|-` separator "
        "is what stops it"
    )


def test_find_constituency_row_returns_none_when_constituency_absent():
    """A partial article (e.g. mid-declaration) may omit some
    constituencies; the helper must return None rather than crash."""
    assert find_constituency_row(TWO_ROW_TABLE, "City and East") is None


# ---------------------------------------------------------------------------
# extract_template_body / parse_list_seats_election_results — 2016+ summary
# ---------------------------------------------------------------------------

# Minimal `{{Election results}}` shape mirroring 2024's structure. The
# `seatsN_2` field is the list-seat count; `seatsN` is the constituency
# count and must NOT be summed into the list total. Party 6 has zero
# list seats and must be filtered out.
ELECTION_RESULTS_TEMPLATE = """\
{{Election results
|image=[[File:Synth.svg]]
|firstround=Constituency
|secondround=Party
|party1=[[Labour Party (UK)|Labour]]||votes1=983216||votes1_2=951056|seats1=10|seats1_2=1|totseats1=11|sc1=0
|party2=[[Conservative Party (UK)|Conservative]]|votes2=673036|votes2_2=648269|seats2=3|seats2_2=5|totseats2=8|sc2=-1
|party3=[[London Green Party|Green]]|votes3=319869|votes3_2=286746|seats3=0|seats3_2=3|totseats3=3|sc3=0
|party4=[[Liberal Democrats (UK)|Liberal Democrats]]|votes4=271049|votes4_2=215682|seats4=1|seats4_2=1|totseats4=2|sc4=0
|party5=[[Reform UK]]|votes5=183361|votes5_2=145409|seats5=0|seats5_2=1|totseats5=1|sc5=+1
|party6=[[Rejoin EU]]|votes6_2=62528|seats6_2=0|totseats6=0|sc6=0
}}
"""


def test_parse_list_seats_election_results_sums_to_eleven():
    """The 11-seat d'Hondt allocation is the AC for the tooltip. A
    regression that double-counts `seatsN` would push the total above
    11; a regression that loses `seatsN_2` would push it below."""
    result = parse_list_seats_election_results(ELECTION_RESULTS_TEMPLATE)
    assert result is not None
    seats_norm, _ = result
    assert sum(seats_norm.values()) == 11


def test_parse_list_seats_election_results_skips_zero_seat_parties():
    """`Rejoin EU` has `seats6_2=0` and must not appear in either dict —
    a tooltip line that listed every fielded party (including 0-seat
    minor parties) would be unreadable."""
    seats_norm, seats_raw = parse_list_seats_election_results(
        ELECTION_RESULTS_TEMPLATE
    )
    assert "Rejoin EU" not in seats_raw
    # The five non-zero parties are present
    assert set(seats_raw) == {
        "Labour", "Conservative", "Green", "Liberal Democrats", "Reform UK",
    }


def test_parse_list_seats_election_results_preserves_raw_labels():
    """seats_raw must keep the Wikipedia-side labels so the renderer's
    GLA_ASSEMBLY_RAW_DISPLAY map can pick distinct short-forms (e.g.
    UKIP 2016 / Reform 2024). Collapsing to normalised labels would
    flatten historically distinct minor-party wins to 'Other'."""
    _, seats_raw = parse_list_seats_election_results(ELECTION_RESULTS_TEMPLATE)
    assert seats_raw["Reform UK"] == 1
    assert seats_raw["Liberal Democrats"] == 1
    assert seats_raw["Conservative"] == 5


def test_parse_list_seats_election_results_returns_none_when_template_absent():
    """No template → None, not crash. A real article without an
    `{{Election results}}` block (e.g. 2012) is meant to fall through
    to parse_list_seats_ams_summary."""
    assert parse_list_seats_election_results("no template here") is None


def test_extract_template_body_handles_nested_templates():
    """Brace-balanced scanning must descend into nested `{{…}}` (e.g.
    `[[File:Synth.svg]]` is not nested, but `{{party color|…}}` and
    `{{increase}}…` are common). A naive `.find('}}')` would terminate
    at the first inner close and produce a truncated body."""
    body = extract_template_body(
        "{{Election results|x={{nested|y=1}}|done=yes}}",
        ELECTION_RESULTS_OPEN_RE,
    )
    assert body is not None
    assert "done=yes" in body, (
        "brace-balanced scanner must walk past the nested {{nested|...}} "
        "close before declaring the outer template finished"
    )


# ---------------------------------------------------------------------------
# parse_list_seats_ams_summary — 2012 fallback shape
# ---------------------------------------------------------------------------

# Real 2012 wikitext shape: per-party `{{AMS Election Summary Party}}`
# blocks. `seats` is the constituency count; `AMS seats` is the list
# count. `{{increase}}` / `{{decrease}}` / `{{nochange}}` are nested
# templates whose `}}` must not break the brace-aware block iterator.
AMS_SUMMARY_2012 = """\
{{AMS Election Summary Party|
  |party         = Labour Party (UK)
  |votes         = 933,438
  |seats         = 8
  |seats net     = {{increase}}2
  |AMS seats     = 4
  |AMS seats net = {{increase}}2
}}
{{AMS Election Summary Party|
  |party         = Conservative Party (UK)
  |votes         = 722,280
  |seats         = 6
  |seats net     = {{decrease}}2
  |AMS seats     = 3
  |AMS seats net = {{nochange}}
}}
{{AMS Election Summary Party|
  |party         = Green Party of England and Wales
  |votes         = 188,623
  |seats         = 0
  |AMS seats     = 2
}}
{{AMS Election Summary Party|
  |party         = Liberal Democrats (UK)
  |votes         = 193,842
  |seats         = 0
  |AMS seats     = 2
}}
"""


def test_parse_list_seats_ams_summary_sums_to_eleven():
    """The 2012 list seats split 4 Lab / 3 Con / 2 Green / 2 LibDem = 11.
    A regex that grabbed `seats` instead of `AMS seats` would yield 14
    (constituency total) and a regression that mis-handled the nested
    `{{increase}}` block close would drop later parties."""
    result = parse_list_seats_ams_summary(AMS_SUMMARY_2012)
    assert result is not None
    seats_norm, _ = result
    assert sum(seats_norm.values()) == 11


def test_parse_list_seats_ams_summary_preserves_raw_uk_labels():
    """2012's raw labels include `(UK)` suffixes and `Green Party of
    England and Wales`. seats_raw must keep them so the renderer's
    GLA_ASSEMBLY_RAW_DISPLAY can short-form them consistently."""
    _, seats_raw = parse_list_seats_ams_summary(AMS_SUMMARY_2012)
    assert seats_raw["Labour Party (UK)"] == 4
    assert seats_raw["Conservative Party (UK)"] == 3
    assert seats_raw["Green Party of England and Wales"] == 2
    assert seats_raw["Liberal Democrats (UK)"] == 2


def test_parse_list_seats_ams_summary_returns_none_when_absent():
    """Articles with no `{{AMS Election Summary Party}}` blocks (i.e.
    every year from 2016 onwards) must return None so the caller falls
    through to the 2016+ parser without a false positive."""
    assert parse_list_seats_ams_summary("no AMS template at all") is None
