"""Tests for the time-slider pipeline (issue #70 phase 1A):
  - 04d_build_ward_history.py output shape + invariants
  - 11_extract_current.py refactor preserves byte-identical output
  - 07d_build_current_map_artifact.py --region=gm is byte-identical with
    or without ward_history.json (the slider is GB-only)

Layer 1 — data invariants paintAtYear depends on (ascending-year history,
          chosen-entry carry-forward semantics).
Layer 2 — structural splice (YEARS + WARD_HISTORY constants land in GB
          artifact; absent from GM artifact).
Layer 3 — refactor regressions (11 byte-identical, 07d --region=gm
          byte-identical with vs. without ward_history.json).
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

SLIDER_YEARS = [2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]


@pytest.fixture(scope="session")
def ward_history():
    """Run 04d if its output is missing or stale against its inputs."""
    out = DATA / "ward_history.json"
    deps = [
        DATA / "all_wards.json",
        DATA / "ward_geoms.json",
        ROOT / "data" / "source" / "councils.yaml",
        ROOT / "data" / "source" / "current_ward_overrides.csv",
    ]

    def stale():
        if not out.exists():
            return True
        t = out.stat().st_mtime
        return any(d.exists() and d.stat().st_mtime > t for d in deps)

    if stale():
        subprocess.run([sys.executable, "scripts/04d_build_ward_history.py"],
                       cwd=ROOT, check=True, capture_output=True)
    return json.loads(out.read_text())


# ---------------------------------------------------------------------------
# Layer 1: data invariants paintAtYear depends on
# ---------------------------------------------------------------------------

def test_ward_history_years_are_sorted_ascending(ward_history):
    """The slider reads YEARS in array order to map index -> year. Out-of-
    order entries would put the slider track in a confusing sequence."""
    years = ward_history["years"]
    assert years == sorted(years), f"YEARS must be ascending, got {years}"


def test_ward_history_years_are_within_slider_range(ward_history):
    """Ward-history stops sit at [2017, 2018, 2019, 2021, 2022, 2023, 2024,
    2025, 2026]. 2020 is excluded (Coronavirus postponement). Issue #88
    extended the range back to 2017 for Welsh + Scottish councils."""
    years = ward_history["years"]
    assert set(years).issubset(SLIDER_YEARS), \
        f"years contain values outside the expected ward-history range: " \
        f"{sorted(set(years) - set(SLIDER_YEARS))}"
    assert 2026 in years, "2026 must always be a slider stop (current state)"


def test_ward_history_entries_sorted_ascending_per_ward(ward_history):
    """paintAtYear walks each ward's history with an early break:
        for (const entry of wh.history) {
            if (entry.y <= y) chosen = entry; else break;
        }
    The early break is correct only if history is sorted ascending. A
    misordered entry would cause the slider to paint an older winner when
    a newer one exists at the same slider position."""
    bad = []
    for gss, w in ward_history["wards"].items():
        history = w["history"]
        years = [e["y"] for e in history]
        if years != sorted(years):
            bad.append((gss, years))
            if len(bad) >= 5:
                break
    assert not bad, f"ward histories must be ascending; offenders: {bad}"


def test_ward_history_entry_shape(ward_history):
    """Every history entry must carry y, w, src, url — paintAtYear reads
    .y and .w for fill, wireClicks reads .url for source navigation, and
    the tooltip cites the .src provenance."""
    required = {"y", "w", "src", "url"}
    for gss, w in ward_history["wards"].items():
        for entry in w["history"]:
            missing = required - set(entry)
            assert not missing, \
                f"ward {gss} history entry missing keys {missing}: {entry}"
            assert isinstance(entry["y"], int), \
                f"ward {gss} entry.y must be int, got {type(entry['y'])}"
            assert entry["src"] in ("wiki", "all_wards", "official_ward"), \
                f"ward {gss} entry.src must be one of the known sources, " \
                f"got {entry['src']!r}"


def test_ward_history_carry_forward_matches_paintAtYear(ward_history):
    """The slider's carry-forward logic: at year Y, choose the most-recent
    history entry e where e.y <= Y. This test pins the data structure that
    makes that walk well-defined — for every ward with any history, the
    last-entry-at-2026 must be the entry with the largest y. (If 04d ever
    starts emitting history with descending years, the JS would still pick
    the first-match-from-top and quietly diverge from this invariant.)"""
    mismatched = []
    for gss, w in ward_history["wards"].items():
        history = w["history"]
        if not history:
            continue
        # JS: for each entry, if entry.y <= target, chosen = entry; else break.
        # Equivalent at target=2026 to "the last entry in the ascending list".
        chosen = None
        for entry in history:
            if entry["y"] <= 2026:
                chosen = entry
            else:
                break
        # The "largest y <= 2026" should also be the max year entry (because
        # 2026 is the slider top and SLIDER_YEARS caps at 2026).
        expected = max(history, key=lambda e: e["y"])
        if chosen is not expected:
            mismatched.append((gss, chosen, expected))
            if len(mismatched) >= 3:
                break
    assert not mismatched, \
        f"carry-forward to 2026 must select the max-year entry: {mismatched}"


def test_ward_history_covers_every_geom_ward(ward_history):
    """04d emits an entry for every GB WD24 ward in ward_geoms.json
    (even if history is empty) — paintAtYear's `if (!wh) {...}` fallback
    needs a deterministic universe of GSS codes."""
    geoms = json.loads((DATA / "ward_geoms.json").read_text())
    gb_prefixes = ('E06', 'E07', 'E08', 'E09', 'W06', 'S12')
    gb_geom_gss = {gss for gss, w in geoms["wards"].items()
                   if w["lad"].startswith(gb_prefixes)}
    history_gss = set(ward_history["wards"].keys())
    missing = gb_geom_gss - history_gss
    assert not missing, \
        f"04d dropped {len(missing)} GB wards from ward_history.json " \
        f"(first 5: {sorted(missing)[:5]})"


# ---------------------------------------------------------------------------
# Layer 2: structural splice
# ---------------------------------------------------------------------------

def test_gb_current_ships_slider_constants():
    """The GB artifact must carry both YEARS and WARD_HISTORY constants
    plus the paintAtYear function — a regression in 07d's region gate
    would silently break the slider on production."""
    html = (DOCS / "uk" / "current.html").read_text()
    assert "const YEARS = [" in html, "YEARS constant missing from GB artifact"
    assert "const WARD_HISTORY = {" in html, \
        "WARD_HISTORY constant missing from GB artifact"
    assert "function paintAtYear(" in html, \
        "paintAtYear function missing from GB artifact"
    # The slider chrome lives in hand-authored HTML — confirm it survived.
    assert 'class="time-slider"' in html, \
        "time-slider chrome missing from GB artifact"


def test_gm_current_omits_slider_constants():
    """GM is single-tier and phase 1A is GB-only. The GM artifact must
    NOT ship the slider constants — a regression in 07d's region gate
    would bloat docs/current.html with irrelevant GB ward history."""
    html = (DOCS / "current.html").read_text()
    assert "const YEARS = " not in html, \
        "YEARS constant leaked into GM artifact"
    assert "const WARD_HISTORY = " not in html, \
        "WARD_HISTORY constant leaked into GM artifact"
    assert "function paintAtYear(" not in html, \
        "paintAtYear leaked into GM artifact"


def test_gb_wireTooltips_preserves_county_council_subtitle():
    """fmtTitle (the renderer's static title builder) appends a
    "County Council · …" line to every ward in a 2-tier district, and the
    page deck advertises that hovering surfaces the parent CED winner.
    The slider's wireTooltips IIFE rewrites titleEl.textContent on each
    mouseover, so it must explicitly preserve any "County Council · "
    prefixed line(s) from the prior content — otherwise the documented
    2-tier affordance breaks on first hover. This test pins the splice
    that re-appends the snapshot suffix into the rewritten title lines."""
    html = (DOCS / "uk" / "current.html").read_text()
    assert "countySuffix" in html, \
        "wireTooltips no longer snapshots/restores the County Council " \
        "subtitle — the 2-tier ward tooltip will regress on first hover"
    assert "startsWith('County Council · ')" in html, \
        "wireTooltips no longer detects the 'County Council · ' prefix " \
        "when snapshotting the existing title — the regex/prefix likely " \
        "drifted from fmtTitle's emission"


def test_gb_click_handler_only_fires_with_data_url():
    """The click-to-source handler must early-return when data-url is
    absent. Otherwise wards with no recorded source (Bury 2026, thirds
    wards that carry forward from earlier years with no per-contest URL)
    would trigger window.open with an empty/falsy URL. The matching CSS
    rule `.map-svg path.ward[data-url] { cursor: pointer; }` advertises
    the affordance only when the attribute is set — the JS gate must
    line up with that selector."""
    html = (DOCS / "uk" / "current.html").read_text()
    assert "if (!target || !target.dataset.url) return;" in html, \
        "click handler no longer gates window.open on dataset.url — " \
        "an empty URL would open an empty tab"


def test_gb_paintAtYear_clears_data_url_when_chosen_has_none():
    """paintAtYear must `delete el.dataset.url` (not set it to '') when
    the carried-forward history entry has no URL. The CSS rule
    `.map-svg path.ward[data-url] { cursor: pointer; }` matches the
    attribute presence — setting it to '' would still show the pointer
    cursor and advertise a non-functional click. This guards against
    a regression to the older `el.dataset.url = chosen.url || ''` form."""
    html = (DOCS / "uk" / "current.html").read_text()
    assert "el.dataset.url = chosen.url || ''" not in html, \
        "paintAtYear regressed to setting data-url to empty string — " \
        "the pointer cursor will lie on wards with no source URL"
    assert "delete el.dataset.url" in html, \
        "paintAtYear no longer clears data-url when chosen has no url"


# ---------------------------------------------------------------------------
# Layer 3: refactor regressions
# ---------------------------------------------------------------------------

def _md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_11_extract_current_is_deterministic(tmp_path):
    """11_extract_current.py was refactored to call
    _wiki_history.iter_council_year_records instead of doing the per-article
    walk inline. This test pins **determinism** of the refactored script:
    re-running 11 must produce a byte-identical current_winners_raw.json.
    It does NOT verify equivalence to the pre-refactor inline loop — that
    check was done by hand at refactor time (commit 8b04880) by diffing the
    output before and after the helper extraction. Future drift in
    iter_council_year_records' iteration order or parser dispatch is what
    this test catches; it cannot catch a regression introduced by the
    refactor itself."""
    baseline = DATA / "current_winners_raw.json"
    subprocess.run([sys.executable, "scripts/11_extract_current.py"],
                   cwd=ROOT, check=True, capture_output=True)
    baseline_md5 = _md5(baseline)

    subprocess.run([sys.executable, "scripts/11_extract_current.py"],
                   cwd=ROOT, check=True, capture_output=True)
    assert _md5(baseline) == baseline_md5, \
        "11_extract_current.py is non-deterministic — two consecutive runs " \
        "produced different current_winners_raw.json contents. Likely cause: " \
        "_wiki_history.iter_council_year_records changed iteration order or " \
        "the parser dispatch grew a stochastic branch."


def test_07d_gm_byte_identical_with_and_without_ward_history(tmp_path):
    """The AC says: the GM artifact must be byte-identical with or without
    ward_history.json present. 07d gates the slider splice on
    `region == 'gb' and ward_history.get('years')` — this test removes the
    file temporarily and confirms the GM rebuild is unchanged."""
    history = DATA / "ward_history.json"
    backup = tmp_path / "ward_history.json.bak"

    # Snapshot the current GM artifact.
    gm = DOCS / "current.html"
    subprocess.run(
        [sys.executable, "scripts/07d_build_current_map_artifact.py",
         "--region=gm"],
        cwd=ROOT, check=True, capture_output=True,
    )
    with_history_md5 = _md5(gm)

    # Move ward_history.json out of the way; rebuild GM; compare; restore.
    had_history = history.exists()
    if had_history:
        shutil.move(history, backup)
    try:
        subprocess.run(
            [sys.executable, "scripts/07d_build_current_map_artifact.py",
             "--region=gm"],
            cwd=ROOT, check=True, capture_output=True,
        )
        without_history_md5 = _md5(gm)
    finally:
        if had_history:
            shutil.move(backup, history)
            # Re-run to leave docs/current.html in the expected state.
            subprocess.run(
                [sys.executable, "scripts/07d_build_current_map_artifact.py",
                 "--region=gm"],
                cwd=ROOT, check=True, capture_output=True,
            )

    assert with_history_md5 == without_history_md5, \
        "07d --region=gm artifact diverged when ward_history.json was " \
        "removed — the slider splice is leaking into the GM page"
