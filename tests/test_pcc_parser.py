"""Unit tests for the Election-box parser in 30_extract_pcc.

Covers the four moving parts that `_resolve_winner` and
`_extract_votes_per_party` rely on:

  - FPTP 2024 shape: the leading `{{Election box winning candidate with
    party link}}` template is the primary winner source (party + candidate
    in one pass);
  - SV 2012/2016/2021 shape: no winning-candidate template exists, so the
    parser falls back to the tail `{{Election box supplementary vote
    win|hold|gain |winner=...}}` template and recovers the candidate from
    the candidate row whose `|totalpercent=` flags them as the runoff
    winner;
  - SV tail-only fallback: party survives, candidate is null when
    `totalpercent` is absent or unattributable;
  - Highest-votes fallback when both winning-candidate and tail templates
    are absent — defensive against odd article shapes;
  - vote-field priority — `|votes=` (FPTP), then `|r1votes=` (SV first
    round per candidate), then `|fullwidthvotes=` (the shared SV constant
    that would inflate totals if summed across rows);
  - `<ref>...</ref>` stripping inside candidate bodies, which keeps the
    `\\|field=([^|]+)` field-capture pattern reliable when Wikipedia
    embeds a citation whose internal `|`s would otherwise terminate the
    capture;
  - heading detection: wikilinked H3 headings collapse to the alias label
    so the force section maps to the right PFA code;
  - absorbed-section handling: a section with no Election box returns
    `None`, which the build script treats as "force absorbed into a CA
    mayor that year".
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 30's filename starts with a digit — load by spec like test_holyrood_parser.
_spec = importlib.util.spec_from_file_location(
    "pcc_extract", ROOT / "scripts" / "30_extract_pcc.py"
)
pcc_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pcc_extract)

_resolve_winner = pcc_extract._resolve_winner
_extract_votes_per_party = pcc_extract._extract_votes_per_party
_clean_candidate = pcc_extract._clean_candidate
_strip_refs_and_wikilinks = pcc_extract._strip_refs_and_wikilinks
_force_sections = pcc_extract._force_sections
_extract_force_year = pcc_extract._extract_force_year


# ---------------------------------------------------------------------------
# Fixtures: realistic wikitext shapes captured from the four cached PCC
# consolidated articles. Names/numbers are illustrative; the structural
# templates are the contract we're testing.
# ---------------------------------------------------------------------------

# FPTP 2024 shape — leading winning-candidate template followed by losing
# rows and a tail hold/gain template. The winning row carries `|votes=`.
FPTP_2024_BLOCK = """\
{{Election box begin |title=Avon and Somerset PCC election, 2024}}
{{Election box winning candidate with party link
|party     = [[Labour Party (UK)|Labour]]
|candidate = [[Clare Moody]]
|votes     = 120,000
|percentage = 35.0
}}
{{Election box candidate with party link
|party     = [[Conservative Party (UK)|Conservative]]
|candidate = Mark Shelford
|votes     = 95,000
|percentage = 27.7
}}
{{Election box candidate with party link
|party     = [[Liberal Democrats]]
|candidate = Benet Allen
|votes     = 60,000
|percentage = 17.5
}}
{{Election box gain |winner = Labour |loser = Conservative}}
{{Election box end}}
"""


# SV 2016 shape — supplementary vote candidate rows, no winning-candidate
# template. The runoff winner is the row with `|totalpercent=` whose party
# matches the tail `win/hold/gain |winner=` declaration.
SV_2016_BLOCK = """\
{{Election box supplementary vote begin |title=Bedfordshire PCC election, 2016}}
{{Election box supplementary vote candidate with party link
|party        = [[Conservative Party (UK)|Conservative]]
|candidate    = Kathryn Holloway
|r1votes      = 38,000
|r2votes      = 50,000
|totalpercent = 52.5
|fullwidthvotes = 95,238
}}
{{Election box supplementary vote candidate with party link
|party        = [[Labour Party (UK)|Labour]]
|candidate    = Jas Parmar
|r1votes      = 28,000
|r2votes      = 45,238
|totalpercent = 47.5
|fullwidthvotes = 95,238
}}
{{Election box supplementary vote candidate with party link
|party        = [[Liberal Democrats]]
|candidate    = Linda Jack
|r1votes      = 12,500
|fullwidthvotes = 95,238
}}
{{Election box supplementary vote candidate with party link
|party        = [[Independent (politician)|Independent]]
|candidate    = Olly Martins
|r1votes      = 10,000
|fullwidthvotes = 95,238
}}
{{Election box supplementary vote gain |winner = Conservative |loser = Labour}}
{{Election box end}}
"""


# SV tail-only — no `totalpercent` set on any row. The parser must still
# return the winning party from the tail template; candidate falls back to
# the first matching-party row (or None).
SV_TAIL_ONLY_BLOCK = """\
{{Election box supplementary vote begin |title=Some Force PCC election, 2012}}
{{Election box supplementary vote candidate with party link
|party     = [[Labour Party (UK)|Labour]]
|candidate = Top Candidate
|r1votes   = 20,000
}}
{{Election box supplementary vote candidate with party link
|party     = [[Conservative Party (UK)|Conservative]]
|candidate = Other Candidate
|r1votes   = 15,000
}}
{{Election box supplementary vote win |winner = Labour}}
{{Election box end}}
"""


# Highest-votes fallback — defensive shape: no winning-candidate template,
# no tail win/hold/gain. The parser picks the row with the largest
# numeric vote count.
HIGHEST_VOTES_FALLBACK_BLOCK = """\
{{Election box begin |title=Odd Article Shape}}
{{Election box candidate with party link
|party     = [[Independent (politician)|Independent]]
|candidate = Plurality Winner
|votes     = 22,000
}}
{{Election box candidate with party link
|party     = [[Labour Party (UK)|Labour]]
|candidate = Runner Up
|votes     = 18,000
}}
{{Election box end}}
"""


# Ref-stripping fixture — the `<ref>` inside the candidate field carries
# `|`-separated cite-web fields that would terminate the candidate capture
# if refs weren't stripped first.
CANDIDATE_WITH_REF_BLOCK = """\
{{Election box begin |title=Ref Stripping Test}}
{{Election box winning candidate with party link
|party     = [[Labour Party (UK)|Labour]]
|candidate = Real Name<ref>{{cite web|url=https://example.com|title=Citation|date=2024}}</ref>
|votes     = 50,000
}}
{{Election box candidate with party link
|party     = [[Conservative Party (UK)|Conservative]]
|candidate = Loser
|votes     = 30,000
}}
{{Election box gain |winner = Labour |loser = Conservative}}
{{Election box end}}
"""


# Heading dispatch — two force sections back to back. The parser must
# split on H3 headings, collapse the wikilink to its alias label, and
# return one section body per known force code.
TWO_FORCE_ARTICLE = """\
Introduction prose at the top of the article.

=== [[Avon and Somerset Constabulary]] ===
Avon and Somerset's prose.
{{Election box begin |title=Avon and Somerset PCC election, 2024}}
{{Election box winning candidate with party link
|party     = [[Labour Party (UK)|Labour]]
|candidate = Clare Moody
|votes     = 120,000
}}
{{Election box gain |winner = Labour}}
{{Election box end}}

=== [[Bedfordshire Police]] ===
Bedfordshire's prose.
{{Election box begin |title=Bedfordshire PCC election, 2024}}
{{Election box winning candidate with party link
|party     = [[Labour Party (UK)|Labour]]
|candidate = John Tizard
|votes     = 30,000
}}
{{Election box gain |winner = Labour}}
{{Election box end}}

=== Some Unrelated Section ===
Not a force.
"""


# Absorbed-section shape — heading is present (so the consolidated article
# still mentions the force), but no Election box block follows. The
# extractor must return None so the build skips this force-year.
ABSORBED_FORCE_SECTION = """\
There was no election for the Greater Manchester Police as the role of
police and crime commissioner was due to be taken over by the Mayor of
Greater Manchester on 8 May 2017.
"""


# Re-run shape — Wiltshire 2021 in the wild. The H3 force section contains
# the original May 2021 Election box, then an inline H4
# ``==== August 2021 re-run ====`` sub-section with the re-run Election
# box. The May winner was disqualified for a past drink-driving conviction
# and never took office; the seated PCC is the August re-run winner. The
# parser must:
#   (1) keep the H4 child inside the parent H3 body (depth-aware boundary
#       in `_force_sections`), and
#   (2) prefer the *last* Election box in the section (so the re-run
#       wins over the original) in `_extract_force_year`.
RE_RUN_ARTICLE = """\
Top-level prose.

=== [[Wiltshire Police]] ===
Wiltshire 2021 prose.
{{Election box supplementary vote begin |title=2021 Wiltshire PCC election}}
{{Election box supplementary vote candidate with party link
|party     = [[Conservative Party (UK)|Conservative]]
|candidate = Disqualified May Winner
|r1votes   = 50,000
|totalpercent = 55.0
}}
{{Election box supplementary vote candidate with party link
|party     = [[Labour Party (UK)|Labour]]
|candidate = May Runner-up
|r1votes   = 30,000
|totalpercent = 45.0
}}
{{Election box supplementary vote gain |winner = Conservative}}
{{Election box end}}

==== August 2021 re-run ====
Re-run prose explaining the disqualification.
{{Election box supplementary vote begin |title=August 2021 Wiltshire PCC re-run}}
{{Election box supplementary vote candidate with party link
|party     = [[Conservative Party (UK)|Conservative]]
|candidate = Re-run Winner
|r1votes   = 45,000
|totalpercent = 60.0
}}
{{Election box supplementary vote candidate with party link
|party     = [[Labour Party (UK)|Labour]]
|candidate = Re-run Runner-up
|r1votes   = 25,000
|totalpercent = 40.0
}}
{{Election box supplementary vote hold |winner = Conservative}}
{{Election box end}}

=== [[Next Force]] ===
Next force prose.
"""


# ---------------------------------------------------------------------------
# Tests: winner resolution
# ---------------------------------------------------------------------------

def test_resolve_winner_picks_fptp_winning_candidate_template():
    """FPTP path returns party + candidate from the leading winning-candidate
    template. The wikilinked candidate must collapse to its display label."""
    party, candidate = _resolve_winner(_strip_refs_and_wikilinks(FPTP_2024_BLOCK))
    assert party == "Labour"
    assert candidate == "Clare Moody"


def test_resolve_winner_uses_sv_tail_with_totalpercent_tiebreaker():
    """SV blocks have no winning-candidate template. The parser must fall
    back to the tail `|winner=` declaration and recover the candidate from
    the row whose `|totalpercent=` flags them as the runoff winner."""
    block = _strip_refs_and_wikilinks(SV_2016_BLOCK)
    party, candidate = _resolve_winner(block)
    assert party == "Conservative"
    assert candidate == "Kathryn Holloway", (
        "expected the totalpercent-bearing Conservative row to win the "
        "tiebreak, not the first matching-party row"
    )


def test_resolve_winner_returns_party_only_when_totalpercent_absent():
    """A defensively-shaped SV block with no `totalpercent` on any row
    still surfaces the winning party from the tail template; the candidate
    falls back to the first matching-party row's candidate string."""
    party, candidate = _resolve_winner(_strip_refs_and_wikilinks(SV_TAIL_ONLY_BLOCK))
    assert party == "Labour"
    assert candidate == "Top Candidate"


def test_resolve_winner_falls_back_to_highest_votes():
    """No winning-candidate template, no tail template → pick the row with
    the largest vote count as a last-resort guess."""
    party, candidate = _resolve_winner(
        _strip_refs_and_wikilinks(HIGHEST_VOTES_FALLBACK_BLOCK)
    )
    assert party == "Independent"
    assert candidate == "Plurality Winner"


def test_resolve_winner_returns_none_pair_for_empty_block():
    party, candidate = _resolve_winner("")
    assert party is None
    assert candidate is None


# ---------------------------------------------------------------------------
# Tests: per-party vote totals
# ---------------------------------------------------------------------------

def test_extract_votes_includes_fptp_winning_candidate_row():
    """The winning-candidate row carries the winner's own vote count in
    FPTP articles — it must contribute to the per-party total alongside
    the losing-candidate rows."""
    votes = _extract_votes_per_party(_strip_refs_and_wikilinks(FPTP_2024_BLOCK))
    assert votes.get("Labour") == 120_000
    assert votes.get("Conservative") == 95_000
    assert votes.get("LibDem") == 60_000


def test_extract_votes_prefers_r1votes_over_fullwidthvotes_for_sv():
    """SV rows carry both `|r1votes=` (per candidate) and `|fullwidthvotes=`
    (a shared block constant that would inflate totals if summed). The
    parser must pick r1votes when both are present."""
    votes = _extract_votes_per_party(_strip_refs_and_wikilinks(SV_2016_BLOCK))
    assert votes.get("Conservative") == 38_000, (
        "expected the per-candidate r1votes (38,000), not the shared "
        "fullwidthvotes constant (95,238)"
    )
    assert votes.get("Labour") == 28_000
    assert votes.get("LibDem") == 12_500
    assert votes.get("Independent") == 10_000


# ---------------------------------------------------------------------------
# Tests: ref stripping + candidate cleanup
# ---------------------------------------------------------------------------

def test_strip_refs_removes_cite_web_template_inside_candidate_field():
    """A `<ref>{{cite web|...}}</ref>` inside a candidate field embeds
    pipe-separated cite-web args; without stripping, the `|`-anchored field
    capture would terminate at the first cite-web `|`, mangling the name."""
    party, candidate = _resolve_winner(_strip_refs_and_wikilinks(CANDIDATE_WITH_REF_BLOCK))
    assert party == "Labour"
    assert candidate == "Real Name", (
        f"ref stripping must leave the candidate name intact, got {candidate!r}"
    )


def test_clean_candidate_strips_trailing_re_elected_star():
    """The `*` marker in `Sue Mountstevens *` flags re-election in some
    SV articles; it must not survive into the tooltip text."""
    assert _clean_candidate("Sue Mountstevens *") == "Sue Mountstevens"
    assert _clean_candidate("Mark Burns-Williamson  **  ") == "Mark Burns-Williamson"


def test_clean_candidate_passes_plain_text_through():
    assert _clean_candidate("Clare Moody") == "Clare Moody"


# ---------------------------------------------------------------------------
# Tests: heading dispatch
# ---------------------------------------------------------------------------

def test_force_sections_splits_h3_headings_to_known_codes():
    """`_force_sections` must map each `=== [[Wikilink]] ===` heading to
    the corresponding PFA code via the alias map, and only return forces
    whose alias is registered (so unrelated H3 sections like "Background"
    or "Some Unrelated Section" don't leak into the dispatch dict)."""
    alias_map = {
        "Avon and Somerset Constabulary": "E23000036",
        "Bedfordshire Police":            "E23000026",
    }
    sections = _force_sections(TWO_FORCE_ARTICLE, alias_map)
    assert set(sections.keys()) == {"E23000036", "E23000026"}
    # Each section body must include the section's own Election box block
    # and not bleed past into the next heading.
    assert "Clare Moody" in sections["E23000036"]
    assert "John Tizard" not in sections["E23000036"]
    assert "John Tizard" in sections["E23000026"]
    assert "Clare Moody" not in sections["E23000026"]


def test_extract_force_year_returns_none_for_absorbed_section():
    """A section with no Election box block (e.g. the consolidated 2016
    article's Greater Manchester section, which records the role being
    absorbed into the Mayor of Greater Manchester) must surface as None
    so the build script skips the (force, year) cell rather than emitting
    a junk record."""
    assert _extract_force_year(ABSORBED_FORCE_SECTION) is None


def test_extract_force_year_returns_winner_record_for_real_section():
    """End-to-end smoke test: a full FPTP section yields a record with the
    winner party, the cleaned candidate name, and the per-party vote dict."""
    rec = _extract_force_year(FPTP_2024_BLOCK)
    assert rec is not None
    assert rec["w"] == "Labour"
    assert rec["candidate"] == "Clare Moody"
    assert rec["votes"].get("Labour") == 120_000


# ---------------------------------------------------------------------------
# Tests: H4 re-run sub-section handling (Wiltshire 2021 in the wild)
# ---------------------------------------------------------------------------

def test_force_sections_keeps_h4_re_run_inside_parent_h3():
    """An inline H4 sub-section inside an H3 force section must stay inside
    the parent body — otherwise Wiltshire 2021's re-run Election box would
    be excised, leaving the parser with only the May (disqualified) result."""
    alias_map = {"Wiltshire Police": "E23000038", "Next Force": "E_NEXT"}
    sections = _force_sections(RE_RUN_ARTICLE, alias_map)
    body = sections["E23000038"]
    assert "August 2021 re-run" in body, (
        "H4 sub-section must remain inside the parent H3 force body so the "
        "re-run Election box reaches _extract_force_year"
    )
    assert "Re-run Winner" in body
    # And the parent body must not bleed into the next H3 force.
    assert "Next force prose" not in body


def test_extract_force_year_prefers_re_run_box_over_original():
    """Wiltshire 2021 regression: the original May winner was disqualified
    and never took office. The parser must surface the August re-run winner
    (the actual seated PCC), not the May winner."""
    alias_map = {"Wiltshire Police": "E23000038", "Next Force": "E_NEXT"}
    section = _force_sections(RE_RUN_ARTICLE, alias_map)["E23000038"]
    rec = _extract_force_year(section)
    assert rec is not None
    assert rec["candidate"] == "Re-run Winner", (
        f"expected the August re-run winner, got {rec['candidate']!r} "
        "(this is the Wiltshire 2021 / Jonathon Seed regression)"
    )
    # Party is the same across both boxes for Wiltshire 2021, but the
    # per-party vote totals must come from the re-run block, not the May
    # block.
    assert rec["w"] == "Conservative"
    assert rec["votes"].get("Conservative") == 45_000, (
        "votes must come from the re-run Election box, not the original"
    )
