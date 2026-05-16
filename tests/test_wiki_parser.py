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
    _extract_winner_party,
    _top_candidate_by_votes,
    normalize_party,
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
