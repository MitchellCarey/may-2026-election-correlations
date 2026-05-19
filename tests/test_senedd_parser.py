"""Unit tests for the AMS election box + regional-list parser in
15b_extract_senedd_history.

Sibling of test_holyrood_parser.py — same regression shape, but covers
the Welsh-specific divergences from 18b:

  - `AMS_END_RE` accepts both `{{AMS election box end}}` (2021 form) and
    plain `{{Election box end}}` (pre-2021 form);
  - `TAIL_WIN_RE` matches `{{Election box {hold,gain} with party link}}`
    rather than Holyrood's `{{AMS election box win|hold|gain}}`;
  - the brand-new `parse_regional_list` helper that walks each region
    article's `===Regional MSs/AMs elected in YYYY===` wikitable and
    counts `bgcolor={{party color|X}}` markers, preserving both the
    normalised `seats` dict and the raw `seats_raw` dict (the latter
    keeps UKIP-style labels that normalize_party would collapse).
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 15b's filename starts with a digit — load by spec like test_holyrood_parser.
_spec = importlib.util.spec_from_file_location(
    "senedd_extract", ROOT / "scripts" / "15b_extract_senedd_history.py"
)
senedd_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(senedd_extract)

extract_winner = senedd_extract.extract_winner
clean_candidate = senedd_extract.clean_candidate
find_blocks = senedd_extract.find_blocks
parse_regional_list = senedd_extract.parse_regional_list


# 2021 contest with the post-2020 `{{AMS election box end}}` close marker.
# The winner row carries `|winner = yes`, the canonical first-priority
# detection path.
ABERAVON_2021 = """\
{{AMS election box begin |title=[[2021 Senedd election]]: Aberavon}}
{{AMS election box with party link
|party     = [[Welsh Labour]]
|candidate = [[David Rees (Welsh politician)|David Rees]]
|votes     = 10,505
|winner    = yes
}}
{{AMS election box with party link
|party     = [[Plaid Cymru]]
|candidate = Hannah Hughes
|votes     = 3,500
}}
{{Election box hold with party link |winner = Welsh Labour }}
{{AMS election box end|notes=yes}}
"""


# 2016 contest with the pre-2021 plain `{{Election box end}}` close marker.
# AMS_END_RE must match both forms — a regression here drops the 2016
# blocks from `find_blocks` and silently halves coverage.
ABERAVON_2016 = """\
{{AMS election box begin |title=[[2016 National Assembly for Wales election]]: Aberavon}}
{{AMS election box with party link
|party     = [[Welsh Labour]]
|candidate = [[David Rees (Welsh politician)|David Rees]]
|votes     = 9,803
|winner    = yes
}}
{{AMS election box with party link
|party     = [[Plaid Cymru]]
|candidate = Carolyn Edwards
|votes     = 4,099
}}
{{Election box hold with party link |winner = Welsh Labour }}
{{Election box end}}
"""


# Tail-template fallback — no row carries `|winner = yes`, so the parser
# must fall back to the Welsh `{{Election box {hold,gain} with party link
# |winner = ...}}` form (Holyrood's tail is `{{AMS election box
# {win,hold,gain}}}` without the "with party link" suffix).
TAIL_FALLBACK_BLOCK = """\
{{AMS election box begin |title=[[2021 Senedd election]]: Tail Seat}}
{{AMS election box with party link
|party     = [[Welsh Labour]]
|candidate = A Candidate
|votes     = 8,000
}}
{{AMS election box with party link
|party     = [[Plaid Cymru]]
|candidate = Another Person
|votes     = 4,000
}}
{{Election box hold with party link |winner = Welsh Labour }}
{{AMS election box end}}
"""


# Nested-template guard — the winning row carries `{{increase}}` inside
# the candidate body, whose `}}` must not break the brace-aware scanner
# before `|winner = yes` is seen.
NESTED_TEMPLATE_BLOCK = """\
{{AMS election box begin |title=[[2021 Senedd election]]: Nested Seat}}
{{AMS election box with party link
|party     = [[Welsh Labour]]
|candidate = Nested Winner
|votes     = 12,345
|change    = {{increase}}1.7
|winner    = yes
}}
{{AMS election box with party link
|party     = [[Plaid Cymru]]
|candidate = Nested Loser
|votes     = 4,321
}}
{{AMS election box end}}
"""


# Regional-list fixture — 4 list seats split 2 Lab / 1 UKIP / 1 Con.
# UKIP appears under the raw "UK Independence Party" label that
# normalize_party flattens to "Other"; the test confirms `seats_raw`
# preserves the distinction. Realistic shape: section header, narrative
# preamble, then a single wikitable with one bgcolor-tagged row per seat.
NORTH_WALES_REGION_ARTICLE = """\
Some preamble about the region.

===Regional MSs elected in 2016===
The four regional list MSs returned in 2016 were:

{| class="wikitable"
|-
! Name !! Party
|-
| bgcolor={{party color|Welsh Labour}} | Joyce Watson || [[Welsh Labour]]
|-
| bgcolor={{party color|Welsh Labour}} | Eluned Morgan || [[Welsh Labour]]
|-
| bgcolor={{party color|UK Independence Party}} | Nathan Gill || [[UK Independence Party]]
|-
| bgcolor="{{party color|Welsh Conservatives}}" | Mark Isherwood || [[Welsh Conservatives]]
|}

===Regional MSs elected in 2021===
{| class="wikitable"
|-
| bgcolor={{party color|Welsh Conservatives}} | A || Con
|-
| bgcolor={{party color|Welsh Conservatives}} | B || Con
|-
| bgcolor={{party color|Plaid Cymru}} | C || Plaid
|-
| bgcolor={{party color|Welsh Labour}} | D || Lab
|}
"""


def test_extract_winner_picks_winner_marked_row_2021():
    party, candidate = extract_winner(ABERAVON_2021)
    assert party is not None and "Welsh Labour" in party
    assert candidate == "David Rees", (
        f"disambiguated wikilink candidate must clean to 'David Rees', "
        f"got {candidate!r}"
    )


def test_extract_winner_handles_pre_2021_election_box_end_marker():
    """The 2016 form closes with plain `{{Election box end}}` (no AMS prefix).
    A regex that demands `AMS election box end` would drop the block from
    find_blocks and silently halve 2016 coverage."""
    party, candidate = extract_winner(ABERAVON_2016)
    assert party is not None and "Welsh Labour" in party
    assert candidate == "David Rees"


def test_extract_winner_uses_welsh_tail_template_when_no_winner_row():
    """Holyrood's tail template is `{{AMS election box {win,hold,gain}}}`;
    Welsh articles use `{{Election box {hold,gain} with party link}}`.
    The two regexes don't overlap, so reusing 18b's TAIL_WIN_RE here would
    return (None, None) for any constituency without an explicit
    `|winner = yes` row."""
    party, candidate = extract_winner(TAIL_FALLBACK_BLOCK)
    assert party == "Welsh Labour", (
        f"expected tail template to surface Welsh Labour, got {party!r}"
    )
    assert candidate is None


def test_extract_winner_tolerates_nested_templates_in_candidate_row():
    party, candidate = extract_winner(NESTED_TEMPLATE_BLOCK)
    assert party is not None and "Welsh Labour" in party
    assert candidate == "Nested Winner"


def test_clean_candidate_strips_disambiguated_wikilink():
    raw = "[[David Rees (Welsh politician)|David Rees]]"
    assert clean_candidate(raw) == "David Rees"


def test_clean_candidate_strips_bare_wikilink():
    raw = "[[Carwyn Jones]]"
    assert clean_candidate(raw) == "Carwyn Jones"


def test_clean_candidate_passes_plain_text_through():
    assert clean_candidate("Mark Drakeford") == "Mark Drakeford"


def test_find_blocks_spans_both_election_box_end_forms():
    """The two real-world close-marker forms must both register as block
    boundaries. Without the alternation in AMS_END_RE, the 2016 block
    would not appear in the spans list."""
    wt = ABERAVON_2021 + "\n" + ABERAVON_2016
    spans = find_blocks(wt)
    assert len(spans) == 2, (
        f"expected 2 AMS blocks across the 2021 ({{AMS election box end}}) "
        f"and 2016 ({{Election box end}}) close forms, got {len(spans)}"
    )
    assert spans[0][1] <= spans[1][0], "spans must not overlap"


def test_parse_regional_list_counts_one_record_per_target_year():
    records = parse_regional_list(
        NORTH_WALES_REGION_ARTICLE, "North Wales",
        "https://en.wikipedia.org/wiki/North_Wales_(Senedd_electoral_region)",
    )
    years = sorted(r["year"] for r in records)
    assert years == [2016, 2021], (
        f"parse_regional_list must emit one record per TARGET_YEARS section, "
        f"got years={years}"
    )
    for r in records:
        assert r["kind"] == "regional"
        assert r["region"] == "North Wales"


def test_parse_regional_list_2016_seats_total_four_with_ukip_distinction():
    """The 4 list seats split 2 Lab / 1 UKIP / 1 Con. `seats_raw` must keep
    UKIP under its raw `UK Independence Party` label; `seats` collapses it
    to whatever normalize_party returns (typically `Other`). Losing the raw
    label here means the tooltip can no longer show historic UKIP wins."""
    records = parse_regional_list(NORTH_WALES_REGION_ARTICLE, "North Wales", "u")
    r2016 = next(r for r in records if r["year"] == 2016)

    assert sum(r2016["seats_raw"].values()) == 4
    assert r2016["seats_raw"].get("UK Independence Party") == 1, (
        f"seats_raw must preserve the literal 'UK Independence Party' label, "
        f"got seats_raw={r2016['seats_raw']!r}"
    )
    assert r2016["seats_raw"].get("Welsh Labour") == 2
    assert r2016["seats_raw"].get("Welsh Conservatives") == 1

    # `seats` is normalised — its total must still equal 4 (no row is
    # dropped just because its party normalises to "Other").
    assert sum(r2016["seats"].values()) == 4


def test_parse_regional_list_tolerates_quoted_party_color_template():
    """The 2016 fixture quotes the last cell as `bgcolor="{{party color|...}}"`
    while the others use the unquoted form. REGIONAL_PARTY_RE must accept
    both — a quote-strict pattern would silently undercount by one seat."""
    records = parse_regional_list(NORTH_WALES_REGION_ARTICLE, "North Wales", "u")
    r2016 = next(r for r in records if r["year"] == 2016)
    assert sum(r2016["seats"].values()) == 4, (
        f"the quoted `bgcolor=\"{{party color|Welsh Conservatives}}\"` row "
        f"must be counted; got {r2016['seats']!r}"
    )
