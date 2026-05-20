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
parse_regional_list = holyrood_extract.parse_regional_list


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


# Variant A regional-list fixture — `Election box candidate with party link`
# rows with no `|number = N` field, so seat counts must fall back to
# counting `'''bold'''` markers in the candidate field. The 2021 split is
# 4 Lab / 2 Con / 1 Green = 7 list seats, matching Glasgow's real shape.
# Italic `''Name''` (2 quotes) marks "elected via the constituency vote",
# which must NOT be counted toward list seats.
GLASGOW_2021_LIST = """\
===2021 Scottish Parliament election===

==== Additional member results ====
{{Election box begin for list|title=[[2021 Scottish Parliament election]]: Glasgow}}
{{Election box candidate with party link||party=Scottish National Party|candidate=[[Roza Salih]], ''[[Nicola Sturgeon]]'', ''[[Bill Kidd]]'', plain|votes=133,917}}
{{Election box candidate with party link||party=Scottish Labour|candidate='''[[Pauline McNeill]]''', '''[[Anas Sarwar]]''', '''[[Paul Sweeney]]''', '''[[Pam Duncan-Glancy]]''', plain|votes=74,088}}
{{Election box candidate with party link||party=Scottish Conservatives|candidate='''[[Annie Wells]]''', '''[[Sandesh Gulhane]]''', plain|votes=37,027}}
{{Election box candidate with party link||party=Scottish Greens|candidate='''[[Patrick Harvie]]''', plain|votes=21,000}}
{{Election box end}}
"""


# Variant B regional-list fixture — `Election box scottish candidate
# electoral region with party link` rows with explicit `|number = N`.
# Seat counts must come from the `number` field, not from candidate
# bold markers. The 2016 split is 4 Lab / 3 Con = 7 list seats, matching
# Central Scotland's real 2016 shape.
CENTRAL_2016_LIST = """\
===2016 Scottish Parliament election===

==== Additional member results ====
{| class=wikitable
{{Election box scottish candidate electoral region with party link|
  |party  = Scottish National Party
  |number = 0
  |elected =
}}
{{Election box scottish candidate electoral region with party link|
  |party  = Scottish Labour
  |number = 4
  |elected = [[Richard Leonard]] <br /> [[Monica Lennon]] <br /> [[Mark Griffin]] <br /> [[Elaine Smith]]
}}
{{Election box scottish candidate electoral region with party link|
  |party  = Scottish Conservatives
  |number = 3
  |elected = [[Margaret Mitchell]] <br /> [[Graham Simpson]] <br /> [[Alison Harris]]
}}
{{Election box end}}
"""


# Shorthand year-header fixture — Highlands and Islands uses
# `===YYYY election===` without the `Scottish Parliament` qualifier.
# YEAR_SECTION_RE must accept both forms or 4 of 8 region-years go
# unmatched. The 2016 split is 3 Con / 2 Lab / 1 Green / 1 Indep,
# all under raw labels HOLYROOD_RAW_DISPLAY must shorten downstream
# (Conservative Party (UK), Labour Party (UK), Scottish Green Party).
HIGHLANDS_2016_LIST = """\
===2016 election===

==== Additional member results ====
{{Election box begin for list|title=[[2016 Scottish Parliament election]]: Highlands and Islands}}
{{Election box candidate with party link||party=Scottish National Party|candidate=''[[Maree Todd]]'', plain|votes=81,600}}
{{Election box candidate with party link||party=Conservative Party (UK)|candidate='''[[Douglas Ross]]''', '''[[Edward Mountain]]''', '''[[Donald Cameron]]''', plain|votes=44,693}}
{{Election box candidate with party link||party=Labour Party (UK)|candidate='''[[Rhoda Grant]]''', '''[[David Stewart]]''', plain|votes=22,894}}
{{Election box candidate with party link||party=Scottish Green Party|candidate='''[[John Finnie]]''', plain|votes=14,000}}
{{Election box candidate with party link||party=Independent|candidate='''[[Some Person]]''', plain|votes=2,000}}
{{Election box end}}
"""


def test_parse_regional_list_counts_one_record_per_target_year():
    """A fixture covering both 2016 and 2021 must yield exactly two
    records — one per year in REGIONAL_TARGET_YEARS. Years outside the
    target window (2011, 2007, ...) must not appear."""
    wt = (
        GLASGOW_2021_LIST
        + "\n"
        + CENTRAL_2016_LIST
        + "\n===2011 Scottish Parliament election===\n"
        + "{{Election box begin for list}}\n"
        + "{{Election box candidate with party link||party=Scottish Labour|candidate='''X'''|votes=1}}\n"
        + "{{Election box end}}\n"
    )
    records = parse_regional_list(
        wt, "Test Region",
        "https://en.wikipedia.org/wiki/Test_Region_(Scottish_Parliament_electoral_region)",
    )
    years = sorted(r["year"] for r in records)
    assert years == [2016, 2021], (
        f"parse_regional_list must emit one record per REGIONAL_TARGET_YEARS "
        f"section and drop out-of-window years, got years={years}"
    )
    for r in records:
        assert r["kind"] == "regional"
        assert r["region"] == "Test Region"


def test_parse_regional_list_variant_a_falls_back_to_bold_count():
    """Variant A rows omit `|number = N`, so seat counts come from
    counting `'''bold'''` markers in the candidate field. Italic
    `''Name''` (constituency-elected, not list-elected) must not count."""
    records = parse_regional_list(GLASGOW_2021_LIST, "Glasgow", "u")
    r = next(r for r in records if r["year"] == 2021)
    # 4 Lab + 2 Con + 1 Green = 7 list seats. SNP has 0 bold (all
    # italic-marked constituency wins) and must drop out entirely.
    assert sum(r["seats_raw"].values()) == 7, (
        f"Glasgow 2021 list seats must total 7 from bold-count fallback, "
        f"got seats_raw={r['seats_raw']!r}"
    )
    assert r["seats_raw"].get("Scottish Labour") == 4
    assert r["seats_raw"].get("Scottish Conservatives") == 2
    assert r["seats_raw"].get("Scottish Greens") == 1
    assert "Scottish National Party" not in r["seats_raw"], (
        "italic-marked SNP candidates were constituency-elected, not list-"
        f"elected, and must not appear in seats_raw — got {r['seats_raw']!r}"
    )


def test_parse_regional_list_variant_b_uses_number_param():
    """Variant B rows always populate `|number = N`; that field must
    take precedence over any candidate-field counting. The fixture's
    `elected = [[A]] <br /> [[B]] <br /> ...` field is deliberately
    free of bold markup so a regression that ignored `number` would
    fall back to 0 seats per party."""
    records = parse_regional_list(CENTRAL_2016_LIST, "Central Scotland", "u")
    r = next(r for r in records if r["year"] == 2016)
    assert sum(r["seats_raw"].values()) == 7, (
        f"Central 2016 list seats must total 7 from |number = N|, "
        f"got seats_raw={r['seats_raw']!r}"
    )
    assert r["seats_raw"].get("Scottish Labour") == 4
    assert r["seats_raw"].get("Scottish Conservatives") == 3


def test_parse_regional_list_accepts_shorthand_year_header():
    """Highlands and Islands uses `===YYYY election===` without the
    `Scottish Parliament` qualifier. YEAR_SECTION_RE must accept both
    forms — a stricter regex drops the H&I 2016 + 2021 sections and
    silently halves coverage for that region."""
    records = parse_regional_list(HIGHLANDS_2016_LIST, "Highlands and Islands", "u")
    years = [r["year"] for r in records]
    assert years == [2016], (
        f"`===YYYY election===` shorthand must match YEAR_SECTION_RE, "
        f"got years={years}"
    )


def test_parse_regional_list_preserves_raw_party_labels():
    """The on-wiki regional-list rows use the raw `Conservative Party
    (UK)` / `Labour Party (UK)` labels in older articles. seats_raw
    must preserve those verbatim so HOLYROOD_RAW_DISPLAY in 07d can
    shorten them; collapsing to the normalised form here would lose
    the historical distinction."""
    records = parse_regional_list(HIGHLANDS_2016_LIST, "Highlands and Islands", "u")
    r = records[0]
    assert r["seats_raw"].get("Conservative Party (UK)") == 3
    assert r["seats_raw"].get("Labour Party (UK)") == 2
    assert r["seats_raw"].get("Scottish Green Party") == 1
    # The normalised `seats` dict must still total the same seat count;
    # no row is dropped just because its raw label normalises to a
    # value the test doesn't pin (Other / Labour / Conservative).
    assert sum(r["seats"].values()) == sum(r["seats_raw"].values())
