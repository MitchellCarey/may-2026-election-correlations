"""Unit tests for parsers under scripts/_official_parsers/.

The Lincolnshire CC page (issue #67) was the second occurrence of a parser
keying off row position instead of an elected-row marker — the first was
the Wikipedia election-box parser fixed in #63 / PR #65. These fixtures
lock in the contract on the official-source side."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _official_parsers import lincolnshire_html


LINCS_COUNCIL = {
    'lad_code': 'E10000019',
    'name': 'Lincolnshire',
    'official_url': 'https://www.lincolnshire.gov.uk/council-business/elections/2',
}


BOSTON_NORTH = b"""\
<h3>Boston North</h3>
<table><tbody>
<tr><td>BROADHURST</td><td>Michael</td><td>Green</td><td>116</td></tr>
<tr><td>BROOMFIELD-DOUGLAS</td><td>Carol</td><td>Blue Rev.</td><td>40</td></tr>
<tr><td>CLARK</td><td>Carole</td><td>Labour</td><td>143</td></tr>
<tr>
  <td><strong>CULLEN</strong></td>
  <td><strong>Maggie</strong></td>
  <td><strong>Reform UK</strong></td>
  <td><strong>806</strong></td>
</tr>
<tr><td>DANI</td><td>Anton</td><td>Conservative</td><td>327</td></tr>
</tbody></table>
"""


NO_STRONG_FALLBACK = b"""\
<h3>Hypothetical Division</h3>
<table><tbody>
<tr><td>AARDVARK</td><td>Aaron</td><td>Labour</td><td>100</td></tr>
<tr><td>BADGER</td><td>Bertie</td><td>Reform UK</td><td>1,234</td></tr>
<tr><td>CAT</td><td>Catriona</td><td>Conservative</td><td>500</td></tr>
</tbody></table>
"""


COMMA_VOTES = b"""\
<h3>Big Turnout</h3>
<table><tbody>
<tr><td>ALPHA</td><td>A</td><td>Labour</td><td>900</td></tr>
<tr>
  <td><strong>BETA</strong></td>
  <td><strong>B</strong></td>
  <td><strong>Reform UK</strong></td>
  <td><strong>1,527</strong></td>
</tr>
<tr><td>GAMMA</td><td>C</td><td>Conservative</td><td>800</td></tr>
</tbody></table>
"""


def test_picks_strong_wrapped_row_not_alphabetical_first():
    """Lincolnshire's page lists candidates alphabetically by surname, with
    only the elected row's cells wrapped in <strong>. Picking the first <tr>
    yields the alphabetically-earliest surname (Broadhurst/Green/116), not
    the actual winner (Cullen/Reform/806). Regression guard for #67."""
    rows = lincolnshire_html.parse(BOSTON_NORTH, council=LINCS_COUNCIL, year=2025)
    assert len(rows) == 1
    row = rows[0]
    assert row['division'] == 'Boston North'
    assert row['party'] == 'Reform'
    assert row['candidate'] == 'Maggie CULLEN'
    assert row['votes'] == 806


def test_falls_back_to_highest_votes_when_no_strong_row():
    """If a future page rendering ever drops the <strong> wrapping but
    otherwise keeps the format, the parser must not silently regress to
    first-row-wins. Highest votes is the right fallback for single-seat
    FPTP — mirrors the wiki parser fix in PR #65."""
    rows = lincolnshire_html.parse(NO_STRONG_FALLBACK, council=LINCS_COUNCIL, year=2025)
    assert len(rows) == 1
    row = rows[0]
    assert row['party'] == 'Reform'
    assert row['candidate'] == 'Bertie BADGER'
    assert row['votes'] == 1234


def test_handles_comma_separated_votes():
    """Vote tallies > 999 are comma-formatted in the source HTML; the
    strong-row picker and the int conversion must both tolerate the comma."""
    rows = lincolnshire_html.parse(COMMA_VOTES, council=LINCS_COUNCIL, year=2025)
    assert len(rows) == 1
    assert rows[0]['votes'] == 1527
    assert rows[0]['candidate'] == 'B BETA'
