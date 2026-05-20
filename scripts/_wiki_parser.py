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
    r'\{\{\s*Election box winning candidate(?:\s+with party link)?[^}]*?\|\s*party\s*=\s*([^|}\n]+)',
    re.IGNORECASE | re.DOTALL,
)
# Some 2026 articles (Walsall, Sandwell, St Helens, Basingstoke & Deane, several
# London boroughs, …) use plain {{Election box candidate}} templates for every
# candidate including the winner, with no explicit "winning candidate" marker.
# Editors are inconsistent: some boroughs list candidates in vote-rank order,
# but many London boroughs (Kingston, Islington, …) list alphabetically by
# surname. So we enumerate every candidate template in the section and pick the
# one with the highest numeric `votes=` value rather than relying on order.
#
# The numeric-votes guard is also load-bearing for pre-publication placeholder
# articles: every candidate is listed but every `votes=` is empty. A candidate
# with no numeric votes is ignored, so a section where every candidate is a
# placeholder returns no winner (and `_extract_winner_party` falls through to
# the hold/gain template).
CANDIDATE_BLOCK_RE = re.compile(
    r'\{\{\s*Election box candidate\b'
    r'((?:[^{}]|\{\{[^{}]*\}\})*?)'                        # body (one nested template depth)
    r'\}\}',
    re.IGNORECASE | re.DOTALL,
)
PARTY_PARAM_RE = re.compile(r'\|\s*party\s*=\s*([^|}\n]+)', re.IGNORECASE)
VOTES_PARAM_RE = re.compile(r'\|\s*votes\s*=\s*([\d,]+)', re.IGNORECASE)
# Last-resort fallback: hold/gain template's winner= field. Many articles leave
# this field blank (the template only flags the seat as a hold), so this is
# checked after the candidate-template scan and a blank match is discarded.
HOLDGAIN_RE = re.compile(
    r'\{\{\s*Election box (?:hold|gain)[^|]*\|[^}]*?winner\s*=\s*([^|}\n]+)',
    re.IGNORECASE | re.DOTALL,
)

# Some 2026 articles (Swindon, Epping Forest) drop the per-ward H3 headings and
# put the {{Election box begin}}…{{Election box end}} blocks directly under the
# H2 ward-results section. Match the begin template and read the ward name from
# its title= parameter. The alternation lets the title contain wikilinks like
# `[[Haydon Wick (ward)|Haydon Wick]]` whose internal `|` would otherwise be
# read as a template-parameter delimiter.
# Match plain {{Election box begin}} as well as variants like
# {{Election box begin no change}} (used in Essex 2026 to flag a hold).
ELECTION_BOX_BEGIN_RE = re.compile(
    r'\{\{\s*Election box begin(?:\s+no change)?\s*\|\s*title\s*=\s*'
    r'((?:\[\[[^\]]*\]\]|[^|}\n])+)',
    re.IGNORECASE,
)
ELECTION_BOX_END_RE = re.compile(r'\{\{\s*Election box end\s*\}\}', re.IGNORECASE)

# Havering 2026's per-ward sections delegate their {{Election box ...}} blocks
# to a separate per-ward Wikipedia article via labeled-section transclusion:
#     {{#section:Beam Park (ward)|2026 Beam Park}}
# When the caller provides a fetch_transclusion callback, parse_article
# substitutes each match with the labeled section content from the target page
# before running the winner-extract pass.
SECTION_RE = re.compile(
    r'\{\{#section:\s*([^|}]+?)\s*\|\s*([^}]+?)\s*\}\}',
    re.IGNORECASE,
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
    if 'scottish national' in s or s == 'snp':
        return 'SNP'
    if 'plaid' in s:
        return 'Plaid'
    if 'independent' in s:
        return 'Independent'
    # Local independent groupings — 2026 dataset classifies these as Independent,
    # so match that for the prior-vs-2026 comparison to be apples-to-apples.
    if s in {'radcliffe first', 'one kearsley', 'heald green ratepayers'}:
        return 'Independent'
    return 'Other'


def _top_candidate_by_votes(section: str) -> str | None:
    """Scan every {{Election box candidate ...}} template in a section and
    return the raw `party=` string of the candidate with the highest numeric
    `votes=` value. Returns None if no candidate has a numeric votes field —
    which is what we want for pre-publication placeholder articles (every
    `votes=` empty), so the caller falls through to the hold/gain fallback."""
    best_party: str | None = None
    best_votes = -1
    for m in CANDIDATE_BLOCK_RE.finditer(section):
        body = m.group(1)
        pm = PARTY_PARAM_RE.search(body)
        vm = VOTES_PARAM_RE.search(body)
        if not pm or not vm:
            continue
        try:
            votes = int(vm.group(1).replace(',', ''))
        except ValueError:
            continue
        if votes > best_votes:
            best_votes = votes
            best_party = pm.group(1)
    return best_party


_WIKITABLE_ROW_SEP_RE = re.compile(r'\n\|-+[^\n]*\n')
_WIKITABLE_CELL_PREFIX_RE = re.compile(r'^\s*(?:align\s*=\s*\w+\s*\|)?\s*')
_WIKITABLE_PARTY_LINK_RE = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]')


def _top_wikitable_elected(section: str) -> str | None:
    """Plain-wikitable fallback for the Caerphilly 2017 format: per-ward
    candidate tables built with `{| class=wikitable ... |}` rather than
    {{Election box}} templates. Each candidate row has the shape
    `|name||party||votes||%||Elected`, where the party cell may carry a
    wikilink ([[Welsh Labour]]) or be plain text (Independent). Multi-member
    rows mark every winning candidate as 'Elected'; pick the highest-votes
    elected row."""
    best_party: str | None = None
    best_votes = -1
    for row in _WIKITABLE_ROW_SEP_RE.split(section):
        if 'Elected' not in row:
            continue
        cells = [c.strip() for c in row.split('||')]
        if len(cells) < 5:
            continue
        if 'Elected' not in cells[4]:
            continue
        party_cell = _WIKITABLE_CELL_PREFIX_RE.sub('', cells[1]).strip()
        if not party_cell:
            continue
        link = _WIKITABLE_PARTY_LINK_RE.search(party_cell)
        party = link.group(1) if link else party_cell
        votes_cell = _WIKITABLE_CELL_PREFIX_RE.sub('', cells[2]).strip()
        try:
            votes = int(votes_cell.replace(',', ''))
        except ValueError:
            continue
        if votes > best_votes:
            best_votes = votes
            best_party = party
    return best_party


def _extract_winner_party(section: str) -> str | None:
    """Return the raw party string for the top-of-poll candidate in a wiki
    section, or None if no candidate template is found. Cascades winning →
    highest-vote candidate → plain-wikitable Elected row → hold/gain templates."""
    m = WINNER_RE.search(section)
    if m:
        return m.group(1)
    top = _top_candidate_by_votes(section)
    if top is not None:
        return top
    top = _top_wikitable_elected(section)
    if top is not None:
        return top
    m = HOLDGAIN_RE.search(section)
    if m and m.group(1).strip():
        return m.group(1)
    return None


_WORD_SEAT_COUNT_RE = re.compile(
    r'\s*\((?:one|two|three|four|five|six|seven|eight|nine|ten)\s+seats?\)\s*$',
    re.IGNORECASE,
)
_WARD_NUMBER_PREFIX_RE = re.compile(
    r'^\s*Ward\s+\d+\s*[:\-–—]\s*',
    re.IGNORECASE,
)


def _clean_ward_name(name: str) -> str:
    """Strip Wikipedia heading/title decorations: collapse wikilinks to their
    visible label, drop inline citation tags (<ref>...</ref> / <ref name=...>),
    drop a trailing ward/constituency suffix (Wigan h4 style), drop a trailing
    seat-count parenthetical like '(2)' or '(3 seats)' or '(one seat)' (Welsh
    2017 multi-member wards), drop a leading 'Ward N:' / 'Ward N —' prefix
    (Glasgow's 2017 STV article). The ref-stripping matters for several county-
    council CED H3 titles (Devon, Hertfordshire, Gloucestershire,
    Worcestershire) that embed citations inside the heading."""
    clean = WIKILINK_RE.sub(r'\1', name)
    # Closed <ref>...</ref> first (greedy across tags), then any unbalanced
    # <ref...>/<ref/>/everything-after-the-opening-<ref left in the title.
    clean = re.sub(r'<ref\b[^>]*?/>', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'<ref\b[^>]*>.*?</ref>', '', clean, flags=re.IGNORECASE | re.DOTALL)
    clean = re.sub(r'<ref\b.*$', '', clean, flags=re.IGNORECASE | re.DOTALL)
    clean = re.sub(r'\s+(ward|constituency)\s*$', '', clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r'\s*\(\d+(?:\s+seats?)?\)\s*$', '', clean).strip()
    clean = _WORD_SEAT_COUNT_RE.sub('', clean).strip()
    clean = _WARD_NUMBER_PREFIX_RE.sub('', clean).strip()
    return clean


# H2 section headers used by English county-council (E10*) articles. The
# 2026 set spans five distinct headings — Hampshire uses plain "Results",
# West Sussex "Results by division", East Sussex "Candidates by authority",
# Essex/Norfolk/Suffolk "Candidates/Results by local authority". The 2021
# priors add "Results by district" (Essex/Suffolk) and "Results by electoral
# division" (Hampshire). Case-insensitive.
COUNTY_H2_RE = re.compile(
    r'^==\s*(?:'
    r'Candidates by local authority|Results by local authority|'
    r'Candidates by authority|Results by authority|'
    r'Candidates by electoral division|Candidates by division|'
    r'Candidates and results by division|'
    r'Division results by district|Division results by local authority|'
    r'Division results(?:\s+for\s+[^=\n]*?)?|'
    r'Election results?(?:\s+by\s+division)?|'
    r'Results by district|Results by division|Results by electoral division|'
    r'Results'
    r')\s*==\s*$',
    re.MULTILINE | re.IGNORECASE,
)


_COUNTY_ANTI_H2_RE = re.compile(
    r'^==\s*(?:'
    r'[^=\n]*[Bb]y[- ][Ee]lections?[^=\n]*'  # any heading containing 'by-election(s)' (Subsequent by-elections, By-elections 2017-2021, …)
    r'|[Pp]ost[- ][Ee]lection[^=\n]*'        # 'Post-election changes' / 'Post election by-elections'
    r'|Composition[^=\n]*'
    r'|Previous composition'
    r'|Council composition'
    r'|Vote share[^=\n]*'
    r'|Summary'
    r'|Results summary'
    r'|Notes'
    r'|References'
    r'|External links'
    r'|See also'
    r'|Changes? [0-9–-]+[^=\n]*'             # 'Changes 2021–2025', 'Changes between 2021 and 2025'
    r')\s*==\s*$',
    re.MULTILINE,
)


def _county_results_section(wt: str) -> str:
    """Concatenate every H2 section that plausibly carries per-CED results.

    Older county articles take several shapes:
      - one results H2 with H3-wrapped per-district detail (modern norm);
      - a summary 'Results' H2 followed by a more-specific 'Derbyshire …
        Results by District' that carries the real per-CED data (Derbyshire
        2017);
      - many narrow district-named H2s — either plaintext H2s like
        '==[[Eastbourne]]==' (East Sussex 2017, Warwickshire 2017) or
        'Division results for [[District]]' (Staffordshire 2017) — with
        Election boxes directly under each.

    Strategy: include every H2 section with ≥ 1 {{Election box begin}}
    inside it, MINUS the anti-patterns (by-elections, composition tables,
    summaries, etc.). That handles all three shapes uniformly without
    enumerating every possible district-name heading.
    """
    h2s = list(H2_RE.finditer(wt))
    if not h2s:
        return ''
    chunks = []
    for i, m in enumerate(h2s):
        line_start = wt.rfind('\n', 0, m.start()) + 1
        line_end = wt.find('\n', m.end())
        line = wt[line_start:line_end if line_end != -1 else len(wt)]
        if _COUNTY_ANTI_H2_RE.match(line):
            continue
        start = m.end()
        end = h2s[i + 1].start() if i + 1 < len(h2s) else len(wt)
        section = wt[start:end]
        if '{{Election box begin' not in section:
            continue
        chunks.append(section)
    return '\n'.join(chunks)


def parse_county_article(_council_name: str, year: int, wt: str) -> dict:
    """Return {district_name: {'party', 'seats_won', 'total_seats'}} for one
    English county-council election article.

    English counties elect electoral divisions, not WD22/24 wards. Wikipedia
    article structure varies (per-district summary tables in Essex/Suffolk;
    bare per-division election boxes in Hampshire/Norfolk/East Sussex/West
    Sussex), so this aggregator works from the per-division detail in every
    case: walk each H3 district section, count winning-party templates
    across the division blocks inside it, and take the top party by seats.
    """
    section = _county_results_section(wt)
    if not section:
        return {}

    h3s = list(re.finditer(r'^===\s*([^=\n]+?)\s*===\s*$', section, re.MULTILINE))
    out: dict[str, dict] = {}
    for i, hm in enumerate(h3s):
        district = _clean_ward_name(hm.group(1).strip())
        body_end = h3s[i + 1].start() if i + 1 < len(h3s) else len(section)
        body = section[hm.end():body_end]

        begins = list(ELECTION_BOX_BEGIN_RE.finditer(body))
        if not begins:
            continue
        seat_counts: dict[str, int] = {}
        for j, bm in enumerate(begins):
            blk_start = bm.end()
            next_begin = begins[j + 1].start() if j + 1 < len(begins) else len(body)
            end_match = ELECTION_BOX_END_RE.search(body, blk_start, next_begin)
            blk_end = end_match.start() if end_match else next_begin
            block = body[blk_start:blk_end]
            party = _extract_winner_party(block)
            if not party:
                continue
            normalized = normalize_party(party)
            seat_counts[normalized] = seat_counts.get(normalized, 0) + 1
        if not seat_counts:
            continue
        # Top party by seats. Ties broken by alphabetical party name — fine
        # for a viz; the actual tie-handling can be revisited if it bites.
        top_party = max(sorted(seat_counts), key=lambda p: seat_counts[p])
        out[district] = {
            'party':       top_party,
            'seats_won':   seat_counts[top_party],
            'total_seats': sum(seat_counts.values()),
            'year':        year,
        }
    return out


def parse_county_article_ceds(_council_name: str, year: int, wt: str) -> dict:
    """Return {ced_name: {'party', 'district', 'year'}} for one English
    county-council election article — sibling to parse_county_article that
    keeps the per-CED detail the aggregator collapses.

    Walks every {{Election box begin|title=CED}} in the combined results
    section (see _county_results_section), emitting one record per CED
    keyed by its title and cleaned with the shared _clean_ward_name helper.
    District context is the nearest preceding H3 (modern county-article
    norm) or empty when the article is flat ('Division results for
    [[District]]' H2-only structure, Staffordshire 2017 style).
    """
    section = _county_results_section(wt)
    if not section:
        return {}

    h3_positions: list[tuple[int, str]] = [
        (hm.start(), _clean_ward_name(hm.group(1).strip()))
        for hm in re.finditer(r'^===\s*([^=\n]+?)\s*===\s*$', section, re.MULTILINE)
    ]

    out: dict[str, dict] = {}
    begins = list(ELECTION_BOX_BEGIN_RE.finditer(section))
    for j, bm in enumerate(begins):
        ced_name = _clean_ward_name(bm.group(1).strip())
        blk_start = bm.end()
        next_begin = begins[j + 1].start() if j + 1 < len(begins) else len(section)
        end_match = ELECTION_BOX_END_RE.search(section, blk_start, next_begin)
        blk_end = end_match.start() if end_match else next_begin
        block = section[blk_start:blk_end]
        party = _extract_winner_party(block)
        if not party:
            continue
        if ced_name in out:
            # First-write wins — guards against the rare summary-table
            # template that re-uses a CED name in a non-result context.
            continue
        district = next(
            (d for pos, d in reversed(h3_positions) if pos < bm.start()), ''
        )
        out[ced_name] = {
            'party':    normalize_party(party),
            'district': district,
            'year':     year,
        }
    return out


# Scottish STV articles use {{STV Election box candidate2}} (or its variant
# without the "2" suffix) blocks inside each ward section. Elected candidates
# are marked by triple-quote bold on the `candidate=` field — that's the
# Wikipedia visual convention these articles all share. We treat any candidate
# template carrying a bolded name as an elected seat for the party named in
# the same template, then take the party with the most elected seats per ward
# (alphabetical tie-break, same convention as parse_county_article).
#
# Single regex over the whole template body lets us require BOTH a party
# field and a bolded candidate field in the same template — without that
# coupling we'd also count non-elected candidates whose stage-N totals
# happen to be bolded.
STV_ELECTED_RE = re.compile(
    r'\{\{STV Election box candidate2?\b'      # template name (with or without "2")
    r'(?:[^{}]|\{\{[^{}]*\}\})*?'              # non-greedy body, allowing one level of nested templates
    r'\|\s*party\s*=\s*([^|}\n]+)'             # party=X
    r'(?:[^{}]|\{\{[^{}]*\}\})*?'
    r"\|\s*candidate\s*=\s*'''[^']+'''",       # candidate='''Bold Name''' → elected
    re.IGNORECASE | re.DOTALL,
)
# Some Scottish articles use a separate `{{STV Election box winning candidate}}`
# template family — keep the older regex as a fallback for those.
STV_WINNING_RE = re.compile(
    r'\{\{(?:STV\s+winning\s+candidate|Single transferable vote winning candidate|'
    r'Election box STV winning candidate|STV winner)'
    r'(?:\s+with\s+party\s+link)?[^}]*?\|\s*party\s*=\s*([^|}\n]+)',
    re.IGNORECASE | re.DOTALL,
)
# Uncontested STV wards (number of candidates = number of seats) sit inside an
# `Election box (winning candidate )?unopposed( candidate)? with party link`
# wrapper — the FPTP-style "unopposed" template re-used in Scottish articles.
# No `candidate='''Bold'''` marker because every candidate is elected by
# definition; we treat each template instance as one elected seat.
STV_UNOPPOSED_RE = re.compile(
    r'\{\{Election box (?:winning candidate )?unopposed(?: candidate)? with party link'
    r'\b[^}]*?\|\s*party\s*=\s*([^|}\n]+)',
    re.IGNORECASE | re.DOTALL,
)


def parse_stv_article(_council_name: str, year: int, wt: str) -> dict:
    """Return {ward_name: {'prior_party', 'prior_year'}} for one STV (Scottish)
    council-election article.

    STV elects 3 or 4 candidates per ward. "Winner per ward" is inherently
    lossy; this picks the party with the most elected seats in each ward,
    alphabetical tie-break — same convention as parse_county_article. Wards
    with no parseable result are omitted (callers render them as no_match).

    Output shape matches parse_article so 11_extract_current can dispatch on
    electoral_system without reshaping.
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
        scan_ranges.insert(0, (0, h2_matches[0].start()))

    out: dict[str, dict] = {}
    for r_start, r_end in scan_ranges:
        segment = wt[r_start:r_end]
        headings = [(m.start(), m.end(), m.group(2).strip())
                    for m in HEADING_RE.finditer(segment)]
        for i, (h_start, h_end, name) in enumerate(headings):
            next_start = headings[i + 1][0] if i + 1 < len(headings) else len(segment)
            section = segment[h_end:next_start]

            seat_counts: dict[str, int] = {}
            for pm in STV_ELECTED_RE.finditer(section):
                normalized = normalize_party(pm.group(1))
                seat_counts[normalized] = seat_counts.get(normalized, 0) + 1
            # Fallback for councils using the older "winning candidate" template.
            if not seat_counts:
                for pm in STV_WINNING_RE.finditer(section):
                    normalized = normalize_party(pm.group(1))
                    seat_counts[normalized] = seat_counts.get(normalized, 0) + 1
            # Fallback for uncontested wards (Highland, Inverclyde, Na h-Eileanan
            # Siar, Shetland 2022) — every candidate template carries `party=`,
            # none is bolded.
            if not seat_counts:
                for pm in STV_UNOPPOSED_RE.finditer(section):
                    normalized = normalize_party(pm.group(1))
                    seat_counts[normalized] = seat_counts.get(normalized, 0) + 1
            if not seat_counts:
                continue

            clean = _clean_ward_name(name)
            if clean in out:
                continue
            top_party = max(sorted(seat_counts), key=lambda p: seat_counts[p])
            out[clean] = {'prior_party': top_party, 'prior_year': year}
    return out


def _resolve_transclusions(section: str, fetch_transclusion) -> str:
    """Replace each {{#section:Page|Label}} call in the section text with the
    fetched labeled-section content (or empty string on failure). No-op if
    the section has no transclusions or no fetcher is provided."""
    if fetch_transclusion is None:
        return section
    return SECTION_RE.sub(
        lambda m: fetch_transclusion(m.group(1).strip(), m.group(2).strip()) or '',
        section,
    )


def parse_article(_council_name: str, year: int, wt: str,
                  fetch_transclusion=None) -> dict:
    """Return {ward_name: {'prior_party', 'prior_year'}} for one election article.

    The 'prior_*' keys are historical — 01b consumes them; 01c reshapes
    on the way out. Kept for backwards compatibility with 01b's existing
    output shape (preserves byte-identical prior_winners.json for GM).

    fetch_transclusion: optional callable (page_title, section_label) -> str|None
    that returns the labeled-section wikitext from a per-ward article. Used by
    01c to follow Havering's {{#section:}} delegations; 01b passes None.
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
        out_before = len(out)
        for i, (h_start, h_end, name) in enumerate(headings):
            next_start = headings[i + 1][0] if i + 1 < len(headings) else len(segment)
            section = segment[h_end:next_start]

            party = _extract_winner_party(section)
            if not party and fetch_transclusion is not None and SECTION_RE.search(section):
                # Section has no inline winner template but does have a
                # {{#section:}} transclusion — resolve and re-extract.
                section = _resolve_transclusions(section, fetch_transclusion)
                party = _extract_winner_party(section)
            if not party:
                continue

            clean = _clean_ward_name(name)
            if clean in out:
                continue
            out[clean] = {'prior_party': normalize_party(party), 'prior_year': year}

        # Fallback for articles that drop the per-ward H3 headings and put
        # {{Election box begin|title=Ward Name}}…{{Election box end}} blocks
        # directly under the H2 (Swindon and Epping Forest 2026). Only fires
        # when the H3/H4 walk yielded nothing in this scan range, so existing
        # heading-structured articles are unaffected.
        if len(out) > out_before:
            continue
        begins = list(ELECTION_BOX_BEGIN_RE.finditer(segment))
        for j, bm in enumerate(begins):
            block_start = bm.end()
            next_begin = begins[j + 1].start() if j + 1 < len(begins) else len(segment)
            end_match = ELECTION_BOX_END_RE.search(segment, block_start, next_begin)
            block_end = end_match.start() if end_match else next_begin
            block = segment[block_start:block_end]
            party = _extract_winner_party(block)
            if not party:
                continue
            clean = _clean_ward_name(bm.group(1).strip())
            if clean in out:
                continue
            out[clean] = {'prior_party': normalize_party(party), 'prior_year': year}
    return out
