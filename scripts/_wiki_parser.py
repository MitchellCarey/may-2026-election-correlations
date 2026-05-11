"""Top-of-poll Wikipedia wikitext parser used by 01b (prior winners) and
01c (2026 results).

Both scrapers want the same thing: the **first** `{{Election box winning
candidate ... |party=PARTY}}` template inside each ward section of an
English local-election article. The template shape is consistent between
years and across thirds/all-out/halves councils, so a single parser
serves both phases.
"""
import re


# H2 sections to skip — anything inside one of these can't contain a
# ward-result heading. In 2022 articles "Changes since 2021" tends to come
# AFTER ward results, but in 2026 articles the same h2 is sometimes the
# *next* section after the result summary and before the per-ward block, so
# we can't just cut at the first occurrence.
H2_SKIP = re.compile(
    r'^(?:by[- ]elections?|changes since|aftermath|references|external links|notes|see also)\b',
    re.IGNORECASE,
)

H2_RE = re.compile(r'^==\s*([^=\n]+?)\s*==\s*$', re.MULTILINE)

# Both h3 (===Ward===) and h4 (====Ward====) — Wigan uses h4 inside h3
# constituency sections.
HEADING_RE = re.compile(r'^(={3,4})\s*([^=\n]+?)\s*\1\s*$', re.MULTILINE)

# 2026 articles often title h3 sections as "=== [[Abbey Road (ward)|Abbey Road]] ==="
# (wikilink to a per-ward article). Strip the wikilink markup down to the visible label.
WIKILINK_RE = re.compile(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]')

# Top-of-poll: first {{Election box winning candidate [with party link]...
# |party=PARTY...}}. The "with party link" suffix is optional — minor parties
# (e.g. "Radcliffe First") without their own Wikipedia article use the
# link-less variant.
WINNER_RE = re.compile(
    r'\{\{Election box winning candidate(?:\s+with party link)?[^}]*?\|\s*party\s*=\s*([^|}\n]+)',
    re.IGNORECASE | re.DOTALL,
)
# Some 2026 articles (Walsall, Sandwell, St Helens, Basingstoke & Deane, …) use
# plain {{Election box candidate}} templates for every candidate including the
# winner, with no explicit "winning candidate" marker. Candidates are listed in
# vote-rank order — the first candidate is the winner. Use this as a fallback
# when WINNER_RE finds nothing.
CANDIDATE_RE = re.compile(
    r'\{\{Election box candidate(?:\s+with party link)?[^}]*?\|\s*party\s*=\s*([^|}\n]+)',
    re.IGNORECASE | re.DOTALL,
)
# Last-resort fallback: hold/gain template's winner= field. Many articles leave
# this field blank (the template only flags the seat as a hold), so this is
# checked after CANDIDATE_RE and a blank match is discarded.
HOLDGAIN_RE = re.compile(
    r'\{\{Election box (?:hold|gain)[^|]*\|[^}]*?winner\s*=\s*([^|}\n]+)',
    re.IGNORECASE | re.DOTALL,
)


def normalize_party(raw: str) -> str:
    """Map Wikipedia party-name strings to the canonical labels used downstream."""
    s = raw.strip().lower().replace('[[', '').replace(']]', '')
    if '|' in s:
        s = s.split('|', 1)[-1].strip()
    if 'labour' in s:
        return 'Labour'
    if 'conservative' in s:
        return 'Conservative'
    if 'liberal democrat' in s or 'lib dem' in s or s == 'libdem':
        return 'LibDem'
    if 'green' in s:
        return 'Green'
    if 'reform' in s:
        return 'Reform'
    if 'independent' in s:
        return 'Independent'
    # Local independent groupings — 2026 dataset classifies these as Independent,
    # so match that for the prior-vs-2026 comparison to be apples-to-apples.
    if s in {'radcliffe first', 'one kearsley', 'heald green ratepayers'}:
        return 'Independent'
    return 'Other'


def parse_article(_council_name: str, year: int, wt: str) -> dict:
    """Return {ward_name: {'prior_party', 'prior_year'}} for one election article.

    The 'prior_*' keys are historical — 01b consumes them; 01c reshapes
    on the way out. Kept for backwards compatibility with 01b's existing
    output shape (preserves byte-identical prior_winners.json for GM).
    """
    h2_matches = list(H2_RE.finditer(wt))
    if not h2_matches:
        scan_ranges = [(0, len(wt))]
    else:
        scan_ranges = []
        for i, m in enumerate(h2_matches):
            sec_end = h2_matches[i + 1].start() if i + 1 < len(h2_matches) else len(wt)
            if H2_SKIP.match(m.group(1).strip()):
                continue
            scan_ranges.append((m.end(), sec_end))
        # Include the article preamble (anything before the first h2). Some
        # short single-section articles put winners there.
        scan_ranges.insert(0, (0, h2_matches[0].start()))

    out = {}
    for r_start, r_end in scan_ranges:
        segment = wt[r_start:r_end]
        headings = [(m.start(), m.end(), m.group(2).strip())
                    for m in HEADING_RE.finditer(segment)]
        for i, (h_start, h_end, name) in enumerate(headings):
            next_start = headings[i + 1][0] if i + 1 < len(headings) else len(segment)
            section = segment[h_end:next_start]

            m = WINNER_RE.search(section) or CANDIDATE_RE.search(section)
            if not m:
                m = HOLDGAIN_RE.search(section)
                if m and not m.group(1).strip():
                    m = None
            if not m:
                continue

            # 2026 headings often wrap the ward name in a wikilink; collapse to
            # just the visible label.
            clean = WIKILINK_RE.sub(r'\1', name)
            # Strip "ward" / "constituency" suffix common in Wigan's h4 names.
            clean = re.sub(r'\s+(ward|constituency)\s*$', '', clean, flags=re.IGNORECASE).strip()
            # Strip trailing "(N)" or "(N seats)" — Wikipedia conventions for
            # the number of seats up for election (e.g. "===Roby (2)===" or
            # "===Underhill (2 seats)==="). Neither is part of the ward name
            # and the ONS WD24 register has no such suffix.
            clean = re.sub(r'\s*\(\d+(?:\s+seats?)?\)\s*$', '', clean).strip()
            if clean in out:
                continue
            out[clean] = {'prior_party': normalize_party(m.group(1)), 'prior_year': year}
    return out
