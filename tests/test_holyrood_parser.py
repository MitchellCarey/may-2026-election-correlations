"""Unit tests for the AMS election box parser in 18b_extract_holyrood_history.

Covers:
  - winner detection via the row-level `|winner = yes` marker
  - winner detection via the tail `{{AMS election box win|hold|gain}}` fallback
  - candidate-name extraction across plain text, bare wikilinks, and
    disambiguated `[[Title|Display]]` wikilinks (regression for the
    truncation bug that left ~19 % of candidate strings as broken
    `[[Foo (Bar)` fragments in holyrood_history_raw.json)
  - brace-aware candidate-row iteration tolerates nested templates like
    `{{increase}}1.7` inside a candidate body
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 18b's filename starts with a digit so a plain `import` won't work — load
# it by spec the same way ad-hoc script tests usually do.
_spec = importlib.util.spec_from_file_location(
    "holyrood_extract", ROOT / "scripts" / "18b_extract_holyrood_history.py"
)
holyrood_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(holyrood_extract)

extract_winner = holyrood_extract.extract_winner
clean_candidate = holyrood_extract.clean_candidate
find_blocks = holyrood_extract.find_blocks


# Real Aberdeen Central 2016 shape — the disambiguated wikilink for the
# winning candidate is the regression case the parser fix targets.
ABERDEEN_CENTRAL_2016 = """\
{{AMS election box begin |title=[[2016 Scottish Parliament election]]: Aberdeen Central}}
{{AMS election box with party link
|party     = [[Scottish National Party]]
|candidate = [[Kevin Stewart (Scottish politician)|Kevin Stewart]]
|votes     = 10,058
|winner    = yes
}}
{{AMS election box with party link
|party     = [[Scottish Conservative Party|Conservative]]
|candidate = Ross Thomson
|votes     = 5,304
}}
{{AMS election box turnout|votes=20000|electorate=50000|percentage=40}}
{{AMS election box hold|winner=SNP}}
{{AMS election box end|notes=yes}}
"""


# Tail-template path: no candidate row carries `winner = yes`, so the
# parser must fall back to the `AMS election box {win,hold,gain}` template.
TAIL_FALLBACK_BLOCK = """\
{{AMS election box begin |title=[[2021 Scottish Parliament election]]: Some Seat}}
{{AMS election box with party link
|party     = [[Scottish National Party]]
|candidate = A Candidate
|votes     = 9,000
}}
{{AMS election box with party link
|party     = Labour
|candidate = Another Person
|votes     = 4,000
}}
{{AMS election box hold|winner=SNP}}
{{AMS election box end}}
"""


# Brace-aware iteration regression — the winning candidate row carries a
# nested `{{increase}}` template whose `}}` must not terminate the outer
# candidate body before the `|winner = yes` line is seen.
NESTED_TEMPLATE_BLOCK = """\
{{AMS election box begin |title=[[2021 Scottish Parliament election]]: Nested Seat}}
{{AMS election box with party link
|party     = [[Scottish National Party]]
|candidate = Nested Winner
|votes     = 12,345
|change    = {{increase}}1.7
|winner    = yes
}}
{{AMS election box with party link
|party     = Labour
|candidate = Nested Loser
|votes     = 4,321
}}
{{AMS election box end}}
"""


def test_extract_winner_picks_winner_marked_row():
    party, candidate = extract_winner(ABERDEEN_CENTRAL_2016)
    assert party is not None and "Scottish National Party" in party
    assert candidate == "Kevin Stewart", (
        f"disambiguated wikilink candidate must clean to 'Kevin Stewart', "
        f"got {candidate!r}"
    )


def test_extract_winner_uses_tail_template_when_no_winner_row():
    party, candidate = extract_winner(TAIL_FALLBACK_BLOCK)
    assert party == "SNP", f"expected tail template to surface SNP, got {party!r}"
    # The tail-fallback path doesn't know which candidate row was the
    # winner, so candidate is intentionally None.
    assert candidate is None


def test_extract_winner_tolerates_nested_templates_in_candidate_row():
    party, candidate = extract_winner(NESTED_TEMPLATE_BLOCK)
    assert party is not None and "Scottish National Party" in party
    assert candidate == "Nested Winner"


def test_clean_candidate_strips_disambiguated_wikilink():
    raw = "[[Kevin Stewart (Scottish politician)|Kevin Stewart]]"
    assert clean_candidate(raw) == "Kevin Stewart"


def test_clean_candidate_strips_bare_wikilink():
    raw = "[[Mark McDonald (politician)]]"
    assert clean_candidate(raw) == "Mark McDonald (politician)"


def test_clean_candidate_passes_plain_text_through():
    assert clean_candidate("Maureen Watt") == "Maureen Watt"


def test_find_blocks_returns_one_span_per_ams_box():
    wt = ABERDEEN_CENTRAL_2016 + "\n" + TAIL_FALLBACK_BLOCK
    spans = find_blocks(wt)
    assert len(spans) == 2, f"expected 2 AMS blocks, got {len(spans)}"
    # Spans must not overlap.
    assert spans[0][1] <= spans[1][0]
