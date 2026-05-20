"""Unit tests for the Wikipedia election-box parser fallback (issue #63).

The CANDIDATE_RE fallback used to assume candidates were listed in vote-rank
order and pick the first one. Many 2026 London-borough articles list
candidates alphabetically by surname instead, so the parser now scans every
candidate template and returns the one with the highest numeric votes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _wiki_parser import (
    _clean_ward_name,
    _extract_winner_party,
    _top_candidate_by_votes,
    normalize_party,
    parse_stv_article,
)


KINGSTON_BERRYLANDS = """\
=== Berrylands ===
{{Election box begin no change|title=[[Berrylands (ward)|Berrylands]] (2)}}
{{Election box candidate with party link no change|party=Reform UK|candidate=Anthony Ayoola|votes=289|percentage=11}}
{{Election box candidate with party link no change|party=Reform UK|candidate=Garfield Bateman|votes=329|percentage=12}}
{{Election box candidate with party link no change|party=Conservative Party (UK)|candidate=Paul Bedforth|votes=654|percentage=24}}
{{Election box candidate with party link no change|party=Labour Party (UK)|candidate=Estelle Buchanan|votes=159|percentage=6}}
{{Election box candidate with party link no change|party=Labour Party (UK)|candidate=Roy Green|votes=148|percentage=5}}
{{Election box candidate with party link no change|party=Green Party of England and Wales|candidate=Joyce Kay|votes=397|percentage=14}}
{{Election box candidate with party link no change|party=Conservative|candidate=Steve Kent|votes=662|percentage=24}}
{{Election box candidate with party link no change|party=Liberal Democrats (UK, 2025)|candidate=Rizwana Malik|votes=1203|percentage=44}}
{{Election box candidate with party link no change|party=Liberal Democrats (UK, 2025)|candidate=Anita Schaper|votes=1331|percentage=48}}
{{Election box candidate with party link no change|party=Green Party of England and Wales|candidate=Philip Smith|votes=317|percentage=12}}
{{Election box end}}
"""


WINNING_CANDIDATE_TEMPLATE = """\
=== Some Ward ===
{{Election box begin|title=Some Ward}}
{{Election box winning candidate with party link|party=Labour|candidate=A Winner|votes=1500}}
{{Election box candidate with party link|party=Conservative|candidate=B Loser|votes=900}}
{{Election box candidate with party link|party=Green|candidate=C Loser|votes=400}}
{{Election box end}}
"""


PLACEHOLDER_ALL_EMPTY_VOTES = """\
=== Bunhill ===
{{Election box begin | title =[[Bunhill (ward)|Bunhill]] (3)}}
{{Election box candidate with party link
|party=Conservative Party (UK)
|candidate=Sara Abey
|votes=
|percentage=
}}
{{Election box candidate with party link
|party=Labour Party (UK)
|candidate=Valerie Bossman-Quarshie
|votes=
|percentage=
}}
{{Election box candidate with party link
|party=Green Party of England and Wales
|candidate=Alan Gutierrez
|votes=
|percentage=
}}
{{Election box end}}
"""


def test_picks_highest_vote_candidate_when_alphabetical():
    """Kingston Berrylands lists candidates alphabetically by surname — the
    first match (Ayoola/Reform/289) is not the winner. The helper must scan
    all candidates and pick Schaper (LibDem, 1331)."""
    raw = _top_candidate_by_votes(KINGSTON_BERRYLANDS)
    assert raw is not None
    assert normalize_party(raw) == "LibDem"


def test_picks_winning_candidate_template_when_present():
    """Articles that use {{Election box winning candidate}} should
    short-circuit at WINNER_RE — the candidate fallback never runs. Regression
    guard for Walsall/Sandwell/St Helens-style articles."""
    raw = _extract_winner_party(WINNING_CANDIDATE_TEMPLATE)
    assert raw is not None
    assert normalize_party(raw) == "Labour"


def test_returns_none_when_all_votes_empty():
    """Pre-publication placeholder articles (e.g. Islington Bunhill in the
    cached wikitext) list every candidate with `votes=` empty. The helper
    must return None so the article doesn't get a bogus winner from the
    alphabetically-first party."""
    assert _top_candidate_by_votes(PLACEHOLDER_ALL_EMPTY_VOTES) is None
    assert _extract_winner_party(PLACEHOLDER_ALL_EMPTY_VOTES) is None


def test_clean_ward_name_strips_word_form_seat_counts():
    """Welsh 2017 multi-member ward articles annotate headings with word-form
    seat counts like '(one seat)' / '(three seats)'. The cleaner must strip
    these so the resulting name keys into geom_by_norm / current_ward_overrides
    the same way the digit-form '(2)' / '(3 seats)' does."""
    assert _clean_ward_name("Alltwen (one seat)") == "Alltwen"
    assert _clean_ward_name("Bryncoch South (two seats)") == "Bryncoch South"
    assert _clean_ward_name("Margam and Taibach (three seats)") == "Margam and Taibach"
    assert _clean_ward_name("Foo (ten seats)") == "Foo"
    assert _clean_ward_name("Foo (TWO SEATS)") == "Foo"


def test_clean_ward_name_strips_leading_ward_number_prefix():
    """Glasgow's 2017 STV article keys ward headings as 'Ward N: Name' /
    'Ward N — Name'. The cleaner must strip the prefix so the resulting name
    matches WD24 directly (or via current_ward_overrides). Covers ASCII
    hyphen, en-dash, and em-dash separators."""
    assert _clean_ward_name("Ward 1: Linn") == "Linn"
    assert _clean_ward_name("Ward 12 - Newlands") == "Newlands"
    assert _clean_ward_name("Ward 3 – Pollokshields") == "Pollokshields"
    assert _clean_ward_name("Ward 8 — Govan") == "Govan"


def test_clean_ward_name_leaves_unrelated_headings_alone():
    """Regression guard for the leading-'Ward N' stripper: it must only fire
    when the heading literally starts with 'Ward <digits><sep>'. Names that
    contain the word 'ward' elsewhere, or use a non-numeric token after
    'Ward', must pass through untouched."""
    assert _clean_ward_name("Ward A: Notional") == "Ward A: Notional"
    assert _clean_ward_name("Forward 1: Other") == "Forward 1: Other"
    assert _clean_ward_name(" Forward 1: Other") == "Forward 1: Other"
    assert _clean_ward_name("Foo Ward 1: Bar") == "Foo Ward 1: Bar"


CAERPHILLY_WIKITABLE_WARD = """\
===Cwm Aber / Aber Valley===
{| class=wikitable style=text-align:right
|+Electorate: 4612, Turnout: 30.81%
|-
!Candidate
!Party
!Votes
!%
!Notes
|-
|align=left|John Taylor||align=left|[[Plaid Cymru]]||990||26.51%||align=left|Elected
|-
|align=left|Lyndon J Binding||align=left|[[Plaid Cymru]]||984||26.35%||align=left|Elected
|-
|align=left|David Zenati-Parsons||align=left|[[Welsh Labour]]||307||8.22%||
|-
|align=left|Ryan Graham Smith||align=left|[[Welsh Conservative Party]]||212||5.68%||
|}
"""


CAERPHILLY_WIKITABLE_PLAIN_PARTY = """\
===Coed Duon / Blackwood===
{| class=wikitable style=text-align:right
|+Electorate: 6178, Turnout: 38.02%
|-
!Candidate
!Party
!Votes
!%
!Notes
|-
|align=left|Kevin Etheridge||align=left|Independent||1,069||16.52%||align=left|Elected
|-
|align=left|Nigel Stuart Dix||align=left|Independent||791||12.23%||align=left|Elected
|-
|align=left|Patricia Cook||align=left|[[Welsh Labour]]||604||9.34%||
|}
"""


def test_extract_winner_picks_highest_votes_elected_row_in_wikitable():
    """Caerphilly 2017 uses bespoke `class=wikitable` markup with an
    'Elected' notes-cell marker instead of {{Election box}} templates.
    The parser must pick the highest-votes elected row's party — both
    elected candidates here are Plaid, so the winner_party is Plaid."""
    assert _extract_winner_party(CAERPHILLY_WIKITABLE_WARD) == "Plaid Cymru"


def test_extract_winner_handles_plain_text_party_in_wikitable():
    """Some Caerphilly wards (e.g. Blackwood) list independent candidates
    with the party cell as plain text ('Independent') rather than a
    wikilink. The parser must still extract the bare-text party."""
    assert _extract_winner_party(CAERPHILLY_WIKITABLE_PLAIN_PARTY) == "Independent"


EAST_AYRSHIRE_ANNICK_CAND_BEFORE_PARTY = """\
==Ward results==
===Annick===
{{STV Election box begin2|title=Annick|numcounts=6}}
{{STV Election box candidate2
|candidate='''John McFadzean'''
|party=Scottish Conservatives
|percentage=36.8
|count1='''2,277'''
}}
{{STV Election box candidate2
|candidate='''Gordon Jenkins'''
|party=Scottish National Party
|percentage=17.4
|count1=1,076
|count6='''1,993'''
}}
{{STV Election box candidate2
|candidate=Eòghann MacColl
|party=Scottish National Party
|percentage=14.9
|count1=925
}}
{{STV Election box candidate2
|candidate='''John McGhee'''
|party=Scottish Labour Party
|percentage=13.5
|count6='''1,207'''
}}
{{STV Election box candidate2
|candidate='''Ellen Freel'''
|party=Independent (politician)
|percentage=12.5
|count6='''1,224'''
}}
{{STV Election box end}}
"""


def test_parse_stv_article_handles_candidate_before_party_field_order():
    """The 2017 East Ayrshire article lists `|candidate=...` before
    `|party=...` inside each STV Election box candidate2 template, the
    reverse of the order every other Scottish 2017 article uses. The
    parser must extract elected candidates regardless of field order;
    in Annick the fixture has 1 Con + 1 SNP + 1 Lab + 1 Ind elected
    (4-way tie at 1 seat each), so Conservative wins via the
    alphabetical tie-break in `max(sorted(seat_counts), key=...)`."""
    result = parse_stv_article("East Ayrshire", 2017, EAST_AYRSHIRE_ANNICK_CAND_BEFORE_PARTY)
    assert "Annick" in result
    assert result["Annick"]["prior_party"] == "Conservative"


def test_parse_stv_article_skips_templates_without_bolded_candidate():
    """Non-elected candidates have `candidate=Plain Name` (no triple-quote
    bold) but still carry a party= field. The new two-step matcher must
    not count them as elected seats — the bolded-candidate probe is the
    coupling that distinguishes winners from losers within a ward."""
    only_loser = """\
==Ward results==
===Annick===
{{STV Election box candidate2
|candidate=Loser Lacey
|party=Scottish Labour Party
|count1=100
}}
"""
    result = parse_stv_article("East Ayrshire", 2017, only_loser)
    assert "Annick" not in result
