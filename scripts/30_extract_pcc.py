"""Parse the four cached PCC consolidated articles into one per-force-year
record and emit data/pcc_history.json.

Reads:
  data/source/wiki_pcc_<year>.json   (output of 29_fetch_pcc_results.py)

Writes:
  data/pcc_history.json
    {
      "years": [2012, 2016, 2021, 2024],
      "forces": {
        "<PFA**CD>": {
          "name":      "Avon and Somerset",
          "country":   "England",
          "absorbed_from": {...} or None,
          "history": [
            {"y": 2012, "w": "Independent",
             "candidate": "Sue Mountstevens",
             "src": "wiki",
             "url": "https://en.wikipedia.org/wiki/2012_England_and_Wales_police_and_crime_commissioner_elections",
             "votes": {"Independent": 95181, "Labour": 60111, ...}},
            ...
          ]
        },
        ...
      }
    }

Format quirks across years:
  - 2012/2016/2021 used the Supplementary Vote system —
    ``{{Election box supplementary vote begin}}`` … ``{{Election box end}}``
    with per-candidate ``{{Election box supplementary vote candidate with
    party link}}`` rows. Vote totals live in ``fullwidthvotes`` /
    ``r1votes`` / ``r2votes`` fields. The winner is declared by a
    ``{{Election box (?:supplementary vote )?(?:win|hold|gain)
    |winner=PARTY}}`` template at the tail of the block.
  - 2024 was contested under First-Past-the-Post —
    ``{{Election box begin}}`` … ``{{Election box end}}`` with a leading
    ``{{Election box winning candidate with party link |party= |candidate=}}``
    template followed by losing candidates and ``{{Election box gain/hold}}``
    at the tail.

Forces absorbed into a CA mayor in a given year carry no Election box block
in the consolidated article (e.g. Greater Manchester in 2016/2021/2024, West
Yorkshire in 2021/2024) — the parser naturally produces no history entry
for those (force, year) cells.
"""
import json
import re
import sys
from pathlib import Path

from _police_forces import POLICE_FORCES, PCC_YEARS, alias_to_code, wiki_year_title
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "pcc_history.json"


# Match any H3 or H4 heading; capture the inside (which may itself be a
# wikilink like ``[[Avon and Somerset Constabulary]]``).
HEADING_RE = re.compile(
    r'^(={3,4})\s*(.+?)\s*\1\s*$',
    re.MULTILINE,
)

# Either FPTP or SV opening template. SV-end uses the plain
# ``{{Election box end}}`` close (no "supplementary vote" suffix on `end`).
BOX_BEGIN_RE = re.compile(
    r'\{\{\s*Election box (?:supplementary vote )?begin\b',
    re.IGNORECASE,
)
BOX_END_RE = re.compile(r'\{\{\s*Election box end\s*\}\}', re.IGNORECASE)

# Any candidate row — covers FPTP `Election box candidate`, FPTP
# `Election box winning candidate`, SV `Election box supplementary vote
# candidate`. The winning-candidate template carries the winner's votes
# in 2024 FPTP articles, so it must contribute to the per-party totals
# alongside the losing-candidate rows.
CANDIDATE_RE = re.compile(
    r'\{\{\s*Election box (?:supplementary vote )?(?:winning )?candidate'
    r'(?:\s+with party link)?'
    r'((?:[^{}]|\{\{[^{}]*\}\})*?)'
    r'\}\}',
    re.IGNORECASE | re.DOTALL,
)

# Winning-candidate template (2024 FPTP only — gives both party and
# candidate; preferred over the tail win/hold/gain template for winner
# resolution).
WINNING_CANDIDATE_RE = re.compile(
    r'\{\{\s*Election box winning candidate(?:\s+with party link)?'
    r'((?:[^{}]|\{\{[^{}]*\}\})*?)'
    r'\}\}',
    re.IGNORECASE | re.DOTALL,
)

# SV / FPTP winner declarations at the tail of the block:
#   {{Election box (?:supplementary vote )?(?:win|hold|gain) |winner = PARTY}}
WINNER_TAIL_RE = re.compile(
    r'\{\{\s*Election box (?:supplementary vote )?(?:win|hold|gain)\b'
    r'[^}]*?\|\s*winner\s*=\s*([^|}\n]+)',
    re.IGNORECASE | re.DOTALL,
)

PARTY_FIELD_RE     = re.compile(r'\|\s*party\s*=\s*([^|\n]+)', re.IGNORECASE)
CANDIDATE_FIELD_RE = re.compile(r'\|\s*candidate\s*=\s*([^|\n]+)', re.IGNORECASE)
# FPTP uses `votes=N` (the candidate's own count). SV uses `r1votes=N` for
# the first-round count per candidate (and `r2votes=N` for the 2 candidates
# in the runoff). `fullwidthvotes` is a shared constant — typically the
# runoff total — that appears identically on every row in the same block,
# so summing it across candidates inflates totals. Prefer `votes` > `r1votes`
# > `fullwidthvotes`.
VOTES_FIELD_RE          = re.compile(r'\|\s*votes\s*=\s*([\d,]+)', re.IGNORECASE)
R1_VOTES_RE             = re.compile(r'\|\s*r1votes\s*=\s*([\d,]+)', re.IGNORECASE)
FULLWIDTH_VOTES_RE      = re.compile(r'\|\s*fullwidthvotes\s*=\s*([\d,]+)', re.IGNORECASE)
# `totalpercent` is only set on the two SV runoff candidates (winner + runner-up).
TOTALPERCENT_RE         = re.compile(r'\|\s*totalpercent\s*=\s*([\d.]+)', re.IGNORECASE)

WIKILINK_RE = re.compile(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]')
# Closed and unclosed <ref>...</ref> blocks. The Wikipedia candidate=
# fields frequently embed cite-web refs whose internal `|` separators
# break a naive `\|...=([^|]+)` capture. Strip refs from the whole
# Election box block before field extraction.
REF_RE = re.compile(r'<ref\b[^>]*?/>|<ref\b[^>]*>.*?</ref>',
                    re.IGNORECASE | re.DOTALL)
# Unclosed tail like `<ref name=...` running to end of input — guard with
# a separate pass after the closed-ref strip.
UNCLOSED_REF_RE = re.compile(r'<ref\b[^>]*>.*$',
                             re.IGNORECASE | re.DOTALL)


def _heading_label(raw: str) -> str:
    """Collapse a heading like ``[[Avon and Somerset Constabulary]]`` to its
    visible label. Wikilinks may be piped; both forms reduce to the label."""
    return WIKILINK_RE.sub(r'\1', raw).strip()


def _clean_candidate(s: str) -> str:
    """Strip a trailing `*` re-elected marker from a candidate name. Refs
    and wikilinks have already been removed at the block level."""
    s = re.sub(r'\s*\*+\s*$', '', s)
    return s.strip()


def _strip_refs_and_wikilinks(block: str) -> str:
    """Remove every <ref>...</ref> block from a wikitext span and expand
    wikilinks down to their visible label. Both transforms make the
    `\\|field=([^|]+)` field-capture pattern reliable: refs introduce
    cite-web `|` separators that would terminate the capture, and piped
    wikilinks like ``[[Sarah Taylor (police commissioner)|Sarah Taylor]]``
    embed a `|` inside the value itself."""
    block = REF_RE.sub('', block)
    block = UNCLOSED_REF_RE.sub('', block)
    block = WIKILINK_RE.sub(r'\1', block)
    return block


def _force_sections(wt: str, alias_map: dict[str, str]) -> dict[str, str]:
    """Return {pfa_code: section_wikitext} by walking H3/H4 headings and
    mapping each matching alias to the body between that heading and the
    next heading of equal or shallower depth.

    Depth-aware boundaries: an H3 force section is terminated only by the
    next H3 (or shallower); H4 children stay inside their parent. This
    keeps inline sub-sections like Wiltshire 2021's
    ``==== August 2021 re-run ====`` inside the parent ``[[Wiltshire
    Police]]`` H3 body so the re-run Election box reaches the parser."""
    headings = list(HEADING_RE.finditer(wt))
    sections: dict[str, str] = {}
    for i, m in enumerate(headings):
        label = _heading_label(m.group(2))
        code = alias_map.get(label)
        if not code:
            continue
        depth = len(m.group(1))
        body_start = m.end()
        body_end = len(wt)
        for j in range(i + 1, len(headings)):
            if len(headings[j].group(1)) <= depth:
                body_end = headings[j].start()
                break
        # If the same force is split across multiple sub-sections (rare),
        # take the first occurrence.
        sections.setdefault(code, wt[body_start:body_end])
    return sections


def _candidate_votes(body: str) -> int | None:
    """Pick the right per-candidate vote count from a candidate-row body."""
    for rx in (VOTES_FIELD_RE, R1_VOTES_RE, FULLWIDTH_VOTES_RE):
        vm = rx.search(body)
        if vm:
            return int(vm.group(1).replace(',', ''))
    return None


def _extract_votes_per_party(block: str) -> dict[str, int]:
    """Walk every candidate row (including the FPTP winning-candidate row),
    collapse vote totals per normalised party."""
    votes: dict[str, int] = {}
    for cm in CANDIDATE_RE.finditer(block):
        body = cm.group(1)
        pm = PARTY_FIELD_RE.search(body)
        if not pm:
            continue
        v = _candidate_votes(body)
        if v is None:
            continue
        party = normalize_party(pm.group(1))
        votes[party] = votes.get(party, 0) + v
    return votes


def _resolve_winner(block: str) -> tuple[str | None, str | None]:
    """Return (winner_party, winner_candidate). The candidate name may be
    ``None`` if we can't recover it (e.g. winner declared by tail template
    only, with the matching candidate row absent or unattributable)."""
    # 1) FPTP "winning candidate" template — gives both party and candidate.
    wc = WINNING_CANDIDATE_RE.search(block)
    if wc:
        body = wc.group(1)
        pm = PARTY_FIELD_RE.search(body)
        cm = CANDIDATE_FIELD_RE.search(body)
        if pm:
            return (
                normalize_party(pm.group(1)),
                _clean_candidate(cm.group(1)) if cm else None,
            )

    # 2) Tail win/hold/gain template — gives party only. Recover the
    # candidate by finding the candidate row whose normalised party matches.
    # For SV cycles, prefer the row with `totalpercent` set (the SV winner)
    # — that row is one of the two runoff candidates, so the row with
    # `totalpercent` AND matching party is the winner.
    tail = WINNER_TAIL_RE.search(block)
    if tail:
        winner_party = normalize_party(tail.group(1))
        fallback: tuple[str, str | None] | None = None
        for cm in CANDIDATE_RE.finditer(block):
            body = cm.group(1)
            pm = PARTY_FIELD_RE.search(body)
            if not pm or normalize_party(pm.group(1)) != winner_party:
                continue
            candm = CANDIDATE_FIELD_RE.search(body)
            cand = _clean_candidate(candm.group(1)) if candm else None
            if TOTALPERCENT_RE.search(body):
                return (winner_party, cand)
            if fallback is None:
                fallback = (winner_party, cand)
        if fallback:
            return fallback
        return (winner_party, None)

    # 3) Fallback — highest-votes candidate.
    best_votes = -1
    best: tuple[str, str | None] | None = None
    for cm in CANDIDATE_RE.finditer(block):
        body = cm.group(1)
        pm = PARTY_FIELD_RE.search(body)
        if not pm:
            continue
        v = _candidate_votes(body)
        if v is None or v <= best_votes:
            continue
        candm = CANDIDATE_FIELD_RE.search(body)
        best_votes = v
        best = (
            normalize_party(pm.group(1)),
            _clean_candidate(candm.group(1)) if candm else None,
        )
    return best if best else (None, None)


def _extract_force_year(section: str) -> dict | None:
    """Find the last Election box block within a force section and parse it.
    Returns None if the section has no Election box (force absorbed into a
    CA mayor that year, or section is purely contextual).

    Last-wins: for Wiltshire 2021, the original May 2021 winner (Jonathon
    Seed) was disqualified for a past drink-driving conviction and never
    took office; the actual seated PCC is Philip Wilkinson, who won the
    19 August 2021 re-run held in the same article's
    ``==== August 2021 re-run ====`` sub-section. Across every other
    (force, year) cell each section carries exactly one Election box, so
    last == first."""
    begins = list(BOX_BEGIN_RE.finditer(section))
    if not begins:
        return None
    bm = begins[-1]
    em = BOX_END_RE.search(section, bm.end())
    if not em:
        return None
    block = _strip_refs_and_wikilinks(section[bm.start():em.end()])
    votes = _extract_votes_per_party(block)
    party, candidate = _resolve_winner(block)
    if not party:
        return None
    return {'w': party, 'candidate': candidate, 'votes': votes}


def main():
    alias_map = alias_to_code()
    code_to_meta = {
        code: (name, country, absorbed)
        for code, name, country, _aliases, absorbed in POLICE_FORCES
    }

    history: dict[str, dict] = {}
    for code, (name, country, absorbed) in code_to_meta.items():
        history[code] = {
            'name':          name,
            'country':       country,
            'absorbed_from': absorbed,
            'history':       [],
        }

    misses: list[str] = []
    per_year_counts: dict[int, int] = {y: 0 for y in PCC_YEARS}
    absorbed_skips: list[tuple[int, str]] = []

    for year in PCC_YEARS:
        cache = SOURCE / f'wiki_pcc_{year}.json'
        if not cache.exists():
            misses.append(f'{year}: missing cache {cache.name}')
            continue
        wt = json.loads(cache.read_text())['parse']['wikitext']
        title = wiki_year_title(year)
        url = (
            'https://en.wikipedia.org/wiki/'
            + title.replace(' ', '_')
        )
        sections = _force_sections(wt, alias_map)
        for code, (name, _country, absorbed) in code_to_meta.items():
            # Forces whose role has been absorbed into a CA mayor by this
            # year don't contest discrete PCC elections — the article may
            # still carry a section discussing the mayoral takeover (and
            # occasionally an Election box for the mayoral contest), but
            # those records belong to a CA-mayor layer, not the PCC layer.
            if absorbed and year >= absorbed['year']:
                absorbed_skips.append((year, name))
                continue
            section = sections.get(code)
            if section is None:
                misses.append(f'{year} {name} ({code}): no section in consolidated article')
                continue
            rec = _extract_force_year(section)
            if rec is None:
                misses.append(f'{year} {name} ({code}): section present but no Election box parsed')
                continue
            history[code]['history'].append({
                'y':         year,
                'w':         rec['w'],
                'candidate': rec['candidate'],
                'src':       'wiki',
                'url':       url,
                'votes':     rec['votes'],
            })
            per_year_counts[year] += 1

    # Sort history entries by year ascending so the renderer's "newest <= y"
    # carry-forward walk works in order.
    for slot in history.values():
        slot['history'].sort(key=lambda e: e['y'])

    out_data = {
        'years':  list(PCC_YEARS),
        'forces': history,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out_data, ensure_ascii=False, indent=2))

    print('Per-year coverage:')
    for y in PCC_YEARS:
        print(f'  {y}: {per_year_counts[y]:>2} / 41 forces')
    n_total = sum(len(f['history']) for f in history.values())
    n_absorbed_skips = len(absorbed_skips)
    print(f'\nTotal force-years parsed: {n_total} '
          f'(+{n_absorbed_skips} absorption skips)')

    if absorbed_skips:
        print('\nAbsorption skips (expected — role exercised by CA mayor):')
        for y, n in absorbed_skips:
            print(f'  {y}  {n}')

    if misses:
        print('\nMisses (unexpected — investigate):', file=sys.stderr)
        for m in misses:
            print(f'  ! {m}', file=sys.stderr)

    print(f'\nWrote {OUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
