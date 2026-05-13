"""Tests for the Current map page: data coverage, spliced artifact shape,
and the chronological z-order comparator from scripts/07d.

Three layers:
  Layer 1 — pipeline coverage: a ratchet on grey-ward counts and anchor
            checks on specific wards backfilled by the issue-#10 work.
  Layer 2 — structural: the spliced HTML/CSS expose the 3-way view picker
            and the year-sorted render block.
  Layer 3 — sort comparator: a Python port of the JS comparator in 07d
            holds the ordering invariants the issue asks for.
"""
import functools
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# Coverage ratchet for GB grey wards. Tightening is fine; loosening should
# raise a flag in review — bump only with justification (e.g. a boundary
# review temporarily un-paints a cohort).
GB_GREY_CEILING = 40


# ---------------------------------------------------------------------------
# Layer 1: pipeline coverage
# ---------------------------------------------------------------------------

def test_gm_fully_coloured(pipeline_outputs):
    """GM has 215 WD24 wards and every one should now carry a winner —
    Bury · Moorside is backfilled from the 2022 article since its 2026
    contest was cancelled."""
    gm = [r for r in pipeline_outputs["winners"]
          if r["lad_code"].startswith("E08") and r["lad_code"] <= "E08000010"]
    assert len(gm) == 215, f"expected 215 GM wards, got {len(gm)}"
    grey = [r for r in gm if r["year"] is None]
    assert grey == [], f"GM should have no grey wards, got: " \
        f"{[(r['borough'], r['ward']) for r in grey]}"


def test_gb_grey_ceiling(pipeline_outputs):
    """Ratchet: don't let the grey count drift back up. Tightening this is
    fine; raising it should require explaining what regressed."""
    grey = [r for r in pipeline_outputs["winners"] if r["year"] is None]
    assert len(grey) <= GB_GREY_CEILING, (
        f"grey ward count is {len(grey)} (ceiling {GB_GREY_CEILING}); "
        f"coverage regressed. New grey clusters: "
        f"{_grey_summary(grey)}"
    )


def _grey_summary(grey_records):
    from collections import Counter
    by_council = Counter((r["lad_code"], r["borough"]) for r in grey_records)
    return ", ".join(f"{name} ({n})" for (_, name), n in by_council.most_common(8))


@pytest.mark.parametrize("lad_code,ward", [
    # Bury Moorside — cancelled 2026, picked up from the 2022 backfill.
    ("E08000002", "Moorside"),
    # Welsh colon-drift fix from current_ward_overrides.csv.
    ("W06000009", "Fishguard: North East"),
    # West Oxfordshire — thirds council whose 2024 article was added.
    ("E07000181", "Witney Central"),
    # Windsor & Maidenhead — article title typo was the gating bug.
    ("E06000040", "Belmont"),
    # Newcastle-under-Lyme — wholly missing wiki_current_articles.
    ("E07000195", "Westlands"),
])
def test_anchor_wards_coloured(pipeline_outputs, lad_code, ward):
    """Specific wards the backfill targeted; regressions here mean the
    override CSV or wiki_current_articles entries got mangled."""
    rec = next((r for r in pipeline_outputs["winners"]
                if r["lad_code"] == lad_code and r["ward"] == ward), None)
    assert rec is not None, f"({lad_code}, {ward!r}) not present in current_winners.json"
    assert rec["winner"] is not None, \
        f"({lad_code}, {ward!r}) lost its winner — coverage regressed"
    assert rec["year"] is not None, \
        f"({lad_code}, {ward!r}) lost its year"


# ---------------------------------------------------------------------------
# Layer 2: structural (spliced HTML/CSS)
# ---------------------------------------------------------------------------

def test_uk_current_has_three_view_buttons():
    html = (DOCS / "uk" / "current.html").read_text()
    for view in ("recent", "wards", "ceds"):
        assert f'data-view="{view}"' in html, f"missing data-view={view!r} button"
    # Default-pressed button is the 'recent' one. Check only that the two
    # attributes coexist in the same <button> tag, not their order/spacing —
    # cosmetic edits to the chrome shouldn't break the test.
    import re
    recent_button = re.search(r'<button\b[^>]*data-view="recent"[^>]*>', html)
    assert recent_button, "missing <button data-view='recent'> tag"
    assert 'aria-pressed="true"' in recent_button.group(0), \
        f"the 'recent' button should start aria-pressed=true; got: {recent_button.group(0)!r}"


def test_gm_current_has_no_view_picker():
    """GM is single-tier — no CEDs, so no picker. The hand-authored chrome
    should never have grown data-view buttons (or stale ced-toggle ones)."""
    html = (DOCS / "current.html").read_text()
    # data-view appears in the spliced JS as a querySelector argument, but
    # not as an HTML attribute. Crude but effective: look for it inside a
    # <button ...> tag, which only happens in hand-authored chrome.
    import re
    button_attrs = re.findall(r"<button\b[^>]*>", html)
    for attrs in button_attrs:
        assert 'data-view=' not in attrs, \
            f"GM page unexpectedly has a data-view button: {attrs!r}"
        assert 'id="ced-toggle"' not in attrs, \
            f"GM page still has the legacy ced-toggle button: {attrs!r}"


def test_shared_css_view_rules():
    css = (DOCS / "shared.css").read_text()
    assert ".map-svg.view-wards path.ced" in css, \
        "missing CSS rule to hide CEDs in wards-only view"
    assert ".map-svg.view-ceds  path.ward" in css or \
           ".map-svg.view-ceds path.ward" in css, \
        "missing CSS rule to hide wards in ceds-only view"
    assert ".show-ceds" not in css, \
        "legacy .show-ceds rule should have been removed"


def test_spliced_js_uses_chronological_sort():
    """The spliced JS in docs/uk/current.html must contain the year-sorted
    items array — the core of the rendering change. We don't pin the exact
    formatting (it's authored in 07d), but the signature should survive
    minor edits."""
    html = (DOCS / "uk" / "current.html").read_text()
    # The sort comparator uses `(a.y ?? 0) - (b.y ?? 0)` — that's the
    # year-ordering signal we want to confirm survived the splice.
    assert "(a.y ?? 0) - (b.y ?? 0)" in html, \
        "chronological sort comparator missing from spliced JS"
    assert "items.sort" in html, "items.sort call missing from spliced JS"
    # Wards-beat-CEDs-on-tie clause.
    assert "a.kind === 'ced'" in html, \
        "ward-vs-CED tie-break missing from spliced JS"


# ---------------------------------------------------------------------------
# Layer 3: sort comparator (Python port of 07d's JS comparator)
# ---------------------------------------------------------------------------

def _cmp(a, b):
    """Python mirror of the JS comparator:
        items.sort((a, b) => (a.y ?? 0) - (b.y ?? 0) || (a.kind === 'ced' ? -1 : 1));
    Returns -1/0/1 so it can feed functools.cmp_to_key."""
    primary = (a["y"] or 0) - (b["y"] or 0)
    if primary:
        return -1 if primary < 0 else 1
    return -1 if a["kind"] == "ced" else 1


def _ordered(*items):
    return sorted(items, key=functools.cmp_to_key(_cmp))


def test_sort_2026_ward_paints_on_top_of_2025_ced():
    ward = {"kind": "ward", "y": 2026, "id": "tw"}
    ced = {"kind": "ced", "y": 2025, "id": "kent"}
    assert _ordered(ced, ward)[-1] == ward, \
        "2026 ward should paint after (= on top of) 2025 CED"


def test_sort_2026_ced_paints_on_top_of_2024_wards():
    ward = {"kind": "ward", "y": 2024, "id": "norwich"}
    ced = {"kind": "ced", "y": 2026, "id": "norfolk"}
    assert _ordered(ward, ced)[-1] == ced, \
        "2026 CED should paint after a 2024 ward underneath it"


def test_sort_ward_beats_ced_on_year_tie():
    ward = {"kind": "ward", "y": 2025, "id": "w"}
    ced = {"kind": "ced", "y": 2025, "id": "c"}
    assert _ordered(ced, ward)[-1] == ward, \
        "wards are more granular and should paint on top on year ties"


def test_sort_null_year_sorts_to_bottom():
    null_ward = {"kind": "ward", "y": None, "id": "grey"}
    ced = {"kind": "ced", "y": 2025, "id": "c"}
    ordered = _ordered(ced, null_ward)
    assert ordered[0] == null_ward, "null-year wards belong at the bottom"
    assert ordered[-1] == ced


def test_sort_full_chronological_chain():
    """The motivating mixed-recency case: a county where one district voted
    in 2026 while the rest still has its 2024 ward winners and a 2025 CED
    overlay. The render must end with the 2026 ward on top."""
    items = [
        {"kind": "ward", "y": 2024, "id": "ward_2024"},
        {"kind": "ced",  "y": 2025, "id": "ced_2025"},
        {"kind": "ward", "y": 2026, "id": "ward_2026"},
    ]
    ordered = _ordered(*items)
    assert [it["id"] for it in ordered] == ["ward_2024", "ced_2025", "ward_2026"]
