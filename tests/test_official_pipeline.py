"""Tests for scripts/13_extract_official.py.

The interesting behaviour is the dedup-on-rewrite logic that decides which
existing CSV rows survive when a parser is re-extracted. A council with a
registered parser can still carry hand-curated supplements for wards the
parser doesn't emit (Wikipedia + official source both silent) — those rows
must survive across re-extracts because they don't share a (lad_code,
normalised_ward) key with anything the parser produced this run.
"""
import csv
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _materialise(tmp_path: Path, councils_yaml: str, fake_parser: str,
                 ward_csv_seed: str) -> Path:
    """Stand up a minimal repo layout the 13 script can run in: scripts/
    is copied (not symlinked — 13 calls Path(__file__).resolve()), and the
    relevant data/source/ files are written fresh.

    `fake_parser` is the body of a one-off parser module dropped into
    scripts/_official_parsers/ that emits a controlled set of rows."""
    work = tmp_path / "work"
    shutil.copytree(REPO / "scripts", work / "scripts")
    (work / "scripts" / "_official_parsers" / "_test_supplement.py").write_text(fake_parser)

    (work / "data" / "source").mkdir(parents=True)
    (work / "data" / "source" / "councils.yaml").write_text(councils_yaml)
    # 13 reads cached fetches from data/source/official_<slug>_<year>.html.
    # Our fake parser ignores cache contents — but the file must exist.
    (work / "data" / "source" / "official_supplementtown_2026.html").write_text("ignored")
    (work / "data" / "source" / "ward_official_2026.csv").write_text(ward_csv_seed)
    return work


def _run_13(work: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/13_extract_official.py"],
        cwd=work, capture_output=True, text=True, check=True,
    )


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


COUNCILS_YAML = textwrap.dedent("""\
    - lad_code: E07TEST1
      name: Supplementtown
      nation: england
      electoral_system: fptp
      wiki_2026: 2026 Supplementtown Borough Council election
      wiki_prior: null
      wiki_current_articles: null
      official_url: "https://example.com/supplementtown/2026"
      official_parser: _test_supplement
      official_year: 2026
    """)

FAKE_PARSER = textwrap.dedent("""\
    extension = 'html'

    def parse(content, *, council, year):
        # Emits two wards. Tests will seed a third ward — 'Heath' — that the
        # parser does NOT emit, asserting that the seeded row survives.
        return [
            {'lad_code': 'E07TEST1', 'council': 'Supplementtown',
             'ward': 'Castle', 'party': 'Labour', 'candidate': 'SMITH J', 'votes': '1234',
             'source': 'example.com'},
            {'lad_code': 'E07TEST1', 'council': 'Supplementtown',
             'ward': 'Riverside', 'party': 'Reform', 'candidate': 'JONES K', 'votes': '987',
             'source': 'example.com'},
        ]
    """)


def test_handcurated_row_survives_when_parser_does_not_emit_that_ward(tmp_path):
    """The motivating case for issue #64 approach (2): a council has a
    parser registered for the wards it covers, but a single ward is missing
    from the parser's source (Wikipedia + ModernGov both silent). A
    hand-curated row for that one ward must survive re-extraction."""
    seed = ("lad_code,council,ward,party,candidate,votes,source\n"
            "E07TEST1,Supplementtown,Castle,Labour,OLD A,1,old\n"        # parser will override
            "E07TEST1,Supplementtown,Heath,Green,CURATED B,500,handcurate\n")  # parser silent → must survive
    work = _materialise(tmp_path, COUNCILS_YAML, FAKE_PARSER, seed)
    _run_13(work)

    rows = _read_csv(work / "data" / "source" / "ward_official_2026.csv")
    by_ward = {(r['lad_code'], r['ward']): r for r in rows}

    # Castle: parser overrode the seeded row.
    assert by_ward[('E07TEST1', 'Castle')]['candidate'] == 'SMITH J'
    # Riverside: parser-emitted, fresh row.
    assert by_ward[('E07TEST1', 'Riverside')]['candidate'] == 'JONES K'
    # Heath: parser-silent, hand-curated row preserved across the re-extract.
    assert by_ward[('E07TEST1', 'Heath')]['candidate'] == 'CURATED B', \
        "hand-curated row for ward not in parser output should survive"


def test_dedup_is_loose_on_and_vs_ampersand(tmp_path):
    """Parsers inconsistently render ' and ' vs ' & ' (moderngov gives one,
    Bradford's bespoke parser gives the other). Hand-curators usually type
    whichever they've seen most recently. The dedup key normalises both
    forms so re-extracting a parser row replaces — not duplicates — a
    seeded row with the equivalent name in the other form."""
    seed = ("lad_code,council,ward,party,candidate,votes,source\n"
            "E07TEST1,Supplementtown,Castle and Moat,Labour,OLD A,1,old\n")
    fake = FAKE_PARSER.replace("'Castle'", "'Castle & Moat'")
    work = _materialise(tmp_path, COUNCILS_YAML, fake, seed)
    _run_13(work)

    rows = _read_csv(work / "data" / "source" / "ward_official_2026.csv")
    castle_rows = [r for r in rows if 'Castle' in r['ward']]
    assert len(castle_rows) == 1, \
        f"expected exactly 1 Castle row after dedup; got {[r['ward'] for r in castle_rows]}"
    assert castle_rows[0]['candidate'] == 'SMITH J', \
        "parser-emitted '& ' form should override hand-curated 'and ' form"
