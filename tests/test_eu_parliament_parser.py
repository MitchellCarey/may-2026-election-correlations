"""Unit tests for the EP election-box + d'Hondt seat-counting parser in
30_extract_eu_parliament.

Sibling of test_senedd_parser.py / test_holyrood_parser.py — same
fixture-driven regression shape, scoped to the two extraction-specific
risks 30's own docstring calls out:

  - `iter_candidate_bodies` is a brace-balanced walker. Some 2019 rows
    nest two levels of templates inside `change=` (e.g.
    `change={{nowrap|{{increase}}32.46}}`). A single-level regex (the
    simpler form 15 uses for the 2026 Senedd article) silently drops
    those rows — Wales 2019 Brexit Party is the canonical victim.
  - `BOLD_SPAN_RE` is `'''.+?'''` with DOTALL, *not* `'''[^']+?'''`.
    Candidate names contain literal apostrophes ("O'Flynn", "O'Connor")
    that the negated-class form treats as the closing quote and
    silently truncates the span — under-counting that party's seats.
    East of England 2014 UKIP (Patrick O'Flynn) is the canonical victim.

Both regression cases are reproduced as minimal fixtures below so a
future maintainer who unwinds either guard sees the test fail loudly
rather than discovering the under-count in the stderr seat totals.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 30's filename starts with a digit — load by spec the same way the
# Holyrood / Senedd parser tests do.
_spec = importlib.util.spec_from_file_location(
    "ep_extract", ROOT / "scripts" / "30_extract_eu_parliament.py"
)
ep_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ep_extract)

extract_year_block = ep_extract.extract_year_block
iter_candidate_bodies = ep_extract.iter_candidate_bodies
parse_year_block = ep_extract.parse_year_block


# Two-level template nesting inside `change=`. Wales 2019 Brexit Party's
# actual wikitext nests `{{nowrap|{{increase}}…}}` inside the change
# field; a single-level brace walker exits the row when it hits the
# first `}}` and never sees the trailing `|votes=` / `|candidate=` lines.
WALES_2019_NESTED_CHANGE_BLOCK = """\
{{Election box begin for list|title=[[2019 European Parliament election in Wales|2019 European Parliament election]]: Wales}}
{{Election box candidate with party link
|party     = Brexit Party
|candidate = '''Nathan Gill''' (1) <br /> '''James Wells''' (2) <br /> <small>Mandy Jones</small>
|votes     = 271,404
|percentage = 32.5
|change    = {{nowrap|{{increase}}32.46}}
}}
{{Election box candidate with party link
|party     = Plaid Cymru
|candidate = '''Jill Evans''' (3) <br /> <small>Patrick McGuinness</small>
|votes     = 163,928
|percentage = 19.6
|change    = {{increase}}4.3
}}
{{Election box candidate with party link
|party     = Labour Party (UK)
|candidate = '''Jackie Jones''' (4) <br /> <small>Matthew Dorrance</small>
|votes     = 127,833
|percentage = 15.3
|change    = {{decrease}}13.4
}}
{{Election box end}}
"""


# Apostrophe in the bold candidate span. East of England 2014 UKIP led the
# region with Patrick O'Flynn as its top-ranked MEP — a `'''[^']+?'''`
# pattern stops at the apostrophe and silently drops the bold span, so
# UKIP's seat count for the region under-counts by one.
EAST_2014_APOSTROPHE_BLOCK = """\
{{Election box begin for list|title=[[2014 European Parliament election in the East of England|2014 European Parliament election]]: East of England}}
{{Election box candidate with party link
|party     = UK Independence Party
|candidate = '''Patrick O'Flynn''' (1) <br /> '''Stuart Agnew''' (3) <br /> '''Tim Aker''' (5) <br /> <small>Andrew Smith</small>
|votes     = 542,812
|percentage = 34.5
|change    = {{increase}}14.1
}}
{{Election box candidate with party link
|party     = Conservative Party (UK)
|candidate = '''Vicky Ford''' (2) <br /> '''Geoffrey Van Orden''' (4) <br /> '''John Flack''' (6) <br /> <small>Tom Hunt</small>
|votes     = 446,569
|percentage = 28.4
|change    = {{decrease}}3.0
}}
{{Election box candidate with party link
|party     = Labour Party (UK)
|candidate = '''Richard Howitt''' (7) <br /> <small>Sandy Martin</small>
|votes     = 271,601
|percentage = 17.3
|change    = {{increase}}6.6
}}
{{Election box end}}
"""


# Per-year section discovery. Articles use `=== YYYY ===` H3s inside an
# `== Election results ==` H2; `extract_year_block` must return the
# correct year's election box and stop at the next year header.
TWO_YEAR_ARTICLE = """\
Some preamble.

== Election results ==

=== 2014 ===
{{Election box begin for list|title=[[2014 European Parliament election]]: Region}}
{{Election box candidate with party link
|party     = UK Independence Party
|candidate = '''Year 2014 Winner''' (1)
|votes     = 100,000
}}
{{Election box end}}

=== 2019 ===
{{Election box begin for list|title=[[2019 European Parliament election]]: Region}}
{{Election box candidate with party link
|party     = Brexit Party
|candidate = '''Year 2019 Winner''' (1)
|votes     = 200,000
}}
{{Election box end}}
"""


def test_iter_candidate_bodies_tolerates_two_level_nested_change_field():
    """Wales 2019 Brexit Party regression: the brace-balanced walker must
    not exit the row when it encounters the inner `}}` of
    `{{nowrap|{{increase}}…}}` — that would yield only the truncated
    head of the body and lose `votes=` and the bold spans."""
    bodies = list(iter_candidate_bodies(WALES_2019_NESTED_CHANGE_BLOCK))
    assert len(bodies) == 3, (
        f"expected 3 candidate rows (Brexit / Plaid / Labour) after the "
        f"brace-balanced walk, got {len(bodies)}"
    )
    # First body is the Brexit row with the nested change template; the
    # walker must have surfaced the full body including votes / candidate
    # so the parser can see both bold spans.
    brexit_body = bodies[0]
    assert "Brexit Party" in brexit_body
    assert "votes     = 271,404" in brexit_body, (
        "votes= field must survive the nested-template body extraction"
    )
    assert brexit_body.count("'''") == 4, (
        "two bold spans (Nathan Gill, James Wells) must survive — under "
        "single-level brace handling the body truncates before them"
    )


def test_parse_year_block_assigns_two_seats_to_nested_change_row():
    """End-to-end of the Wales 2019 regression: Brexit Party must end up
    with 2 seats (Gill + Wells); under the legacy parser the row body
    truncates at the first nested `}}` and Brexit Party scores 0."""
    seats, seats_raw, votes = parse_year_block(WALES_2019_NESTED_CHANGE_BLOCK)
    assert seats.get("Brexit") == 2, (
        f"Brexit Party must take 2 seats (Gill + Wells); got seats={seats!r}"
    )
    assert seats_raw.get("Brexit Party") == 2
    assert votes.get("Brexit") == 271_404


def test_iter_candidate_bodies_counts_apostrophe_names_as_bold_spans():
    """East 2014 UKIP regression: a `'''[^']+?'''` bold-span pattern stops
    at the apostrophe in `Patrick O'Flynn`, silently dropping that bold
    span and under-counting UKIP's seats."""
    seats, seats_raw, votes = parse_year_block(EAST_2014_APOSTROPHE_BLOCK)
    assert seats.get("UKIP") == 3, (
        f"UKIP must take 3 seats including Patrick O'Flynn; got seats={seats!r}"
    )
    assert seats_raw.get("UK Independence Party") == 3
    assert votes.get("UKIP") == 542_812


def test_parse_year_block_extracts_seats_votes_and_plurality_inputs():
    """Happy path. The East-2014 fixture's 7 seats split 3 UKIP / 3 Con /
    1 Lab; total votes seed the plurality computation in `main`."""
    seats, seats_raw, votes = parse_year_block(EAST_2014_APOSTROPHE_BLOCK)
    assert sum(seats.values()) == 7, (
        f"East of England elected 7 MEPs in 2014; got seats={seats!r}"
    )
    assert seats == {"UKIP": 3, "Conservative": 3, "Labour": 1}
    assert votes == {
        "UKIP":         542_812,
        "Conservative": 446_569,
        "Labour":       271_601,
    }
    # The caller picks the plurality vote winner — confirm the inputs
    # to that selection are correctly ranked here.
    top_party = max(votes, key=lambda p: votes[p])
    assert top_party == "UKIP"


def test_extract_year_block_returns_correct_year_when_multiple_present():
    """The article carries `=== 2014 ===` and `=== 2019 ===` H3s; each
    call must return the requested year's election box, not the other's
    or a span that crosses the boundary."""
    b2014 = extract_year_block(TWO_YEAR_ARTICLE, 2014)
    b2019 = extract_year_block(TWO_YEAR_ARTICLE, 2019)

    assert b2014 is not None and b2019 is not None
    assert "Year 2014 Winner" in b2014
    assert "Year 2019 Winner" not in b2014, (
        "the 2014 block must stop at the next year header so 2019 content "
        "does not leak in"
    )
    assert "Year 2019 Winner" in b2019
    assert "Year 2014 Winner" not in b2019


def test_extract_year_block_returns_none_for_year_not_present():
    """A region that didn't contest a target year (or whose article uses
    a non-standard H3) must surface as None so `main` can log a miss
    rather than parsing a foreign block."""
    assert extract_year_block(TWO_YEAR_ARTICLE, 2009) is None
