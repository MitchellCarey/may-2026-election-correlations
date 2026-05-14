"""Parse the cached 2026 Surrey unitary results into one record per ward.

Three input sources, blended into data/surrey_2026.json:

  1. Wikipedia per-unitary articles
     (data/source/wiki_surrey_<slug>_2026.json, fetched by 22).
     Primary source today for every ward Wikipedia has transcribed —
     i.e. all 36 East Surrey wards plus 23 of the 45 West Surrey wards.
  2. Surrey CC mycouncil moderngov per-ward pages
     (data/source/surrey_council_ward_<area_id>.html, fetched by 22).
     Fills in the 22 still-pending West Surrey wards (issue #42) and
     anywhere else mycouncil has data but Wikipedia doesn't.
  3. Surrey CC electionmap app
     (data/source/surrey_electionmap_<lad_code>.html, fetched by 22).
     Cross-check only — every chosen row must agree with electionmap or
     the script exits non-zero so the user can investigate.

Output schema is unchanged from earlier revisions (07c/07d still
consume data/surrey_2026.json by the same shape):

    {
      "lad_code":  "XSE" | "XSW",
      "lad_name":  "East Surrey" | "West Surrey",
      "ward_code": "<lad>::<slug>",
      "ward_name": "<display name>",
      "winner":    "<party>" | "Pending",
      "seats_won": {"Party": n, ...},
      "winners":   [{"party", "candidate", "votes"}, ...],
      "year":      2026,
      "votes":     {"Party": total, ...},
      "source":    "wiki:<title>" | "surrey-cc:<area_id>"
    }
"""
import html as html_lib
import json
import re
import sys
from pathlib import Path

from _surrey_unitaries import SURREY_COUNCIL_INDEX_URLS, SURREY_UNITARIES
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "surrey_2026.json"

# ---------------------------------------------------------------------------
# Wikipedia parsing (unchanged from the original 23).
# ---------------------------------------------------------------------------

BOX_BEGIN_RE = re.compile(
    r'\{\{\s*Election box begin(?:\s+no change)?\s*\|\s*title\s*=\s*([^|}\n]+?)\s*(?:\||\}\})',
    re.IGNORECASE,
)
BOX_END_RE = re.compile(r'\{\{\s*Election box end\s*\}\}', re.IGNORECASE)

CANDIDATE_TEMPLATE_RE = re.compile(
    r'\{\{\s*Election box (winning\s+)?candidate(?:\s+with party link)?(?:\s+no change)?'
    r'((?:[^{}]|\{\{[^{}]*\}\})*?)'
    r'\}\}',
    re.IGNORECASE | re.DOTALL,
)
PARTY_FIELD_RE = re.compile(r'\|\s*party\s*=\s*([^|\n]+)')
VOTES_FIELD_RE = re.compile(r'\|\s*votes\s*=\s*([\d,]+)')
CANDIDATE_FIELD_RE = re.compile(r'\|\s*candidate\s*=\s*([^|\n]+)')

SEATS_SUFFIX_RE = re.compile(r'\s*\(\d+\s*seats?\)\s*$', re.IGNORECASE)


def _slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def _clean_ward_name(raw: str) -> str:
    s = raw.strip()
    # West Surrey's article embeds <ref>{{Cite web ...}}</ref> inside three
    # title fields; the title regex stops at the first '|' inside the cite
    # template so the capture ends with "<...<ref>{{Cite web". Trim it.
    if '<' in s:
        s = s.split('<', 1)[0].strip()
    return SEATS_SUFFIX_RE.sub('', s).strip()


def _parse_wiki_block(block: str) -> tuple[dict[str, int], dict[str, int], list[dict]]:
    """Return (seats_won, votes_per_party, winners_list) for one Wikipedia ward block."""
    seats: dict[str, int] = {}
    votes: dict[str, int] = {}
    winners: list[dict] = []
    for m in CANDIDATE_TEMPLATE_RE.finditer(block):
        is_winner = bool(m.group(1))
        body = m.group(2)
        pm = PARTY_FIELD_RE.search(body)
        vm = VOTES_FIELD_RE.search(body)
        cm = CANDIDATE_FIELD_RE.search(body)
        if not pm:
            continue
        party = normalize_party(pm.group(1))
        v = int(vm.group(1).replace(',', '')) if vm else 0
        votes[party] = votes.get(party, 0) + v
        if is_winner:
            seats[party] = seats.get(party, 0) + 1
            winners.append({
                'party': party,
                'candidate': cm.group(1).strip() if cm else None,
                'votes': v,
            })
    return seats, votes, winners


def parse_wikipedia(wt: str) -> list[tuple[str, dict, dict, list[dict]]]:
    """Return [(ward_name, seats, votes, winners), ...] for one unitary's article."""
    rows: list[tuple[str, dict, dict, list[dict]]] = []
    pos = 0
    while True:
        bm = BOX_BEGIN_RE.search(wt, pos)
        if not bm:
            break
        em = BOX_END_RE.search(wt, bm.end())
        if not em:
            print(f'  ! Wikipedia: no matching Election box end for {bm.group(1)!r}',
                  file=sys.stderr)
            break
        ward = _clean_ward_name(bm.group(1))
        block = wt[bm.end():em.start()]
        seats, votes, winners = _parse_wiki_block(block)
        rows.append((ward, seats, votes, winners))
        pos = em.end()
    return rows


# ---------------------------------------------------------------------------
# Surrey CC mycouncil per-ward parsing.
# ---------------------------------------------------------------------------

# mycouncil's per-ward results table: one <tr> per candidate. The five
# <td>s are candidate-with-party-swatch / party / votes / pct / outcome.
# The outcome cell's class is "mgMainTxtBold" for elected, "mgTopText"
# for not-elected — match either via an alternation so we capture both
# types of row and can compute votes-per-party correctly. Pattern shape
# mirrors scripts/_official_parsers/moderngov_per_division.py:40-47, but
# with re.finditer over multi-member wards and a wider outcome match.
COUNCIL_ROW_RE = re.compile(
    r'<td[^>]*class="mgTopText"[^>]*>(?:<span[^>]*>.*?</span>\s*)?([^<]+?)</td>\s*'
    r'<td[^>]*class="mgBottomText"[^>]*>([^<]+?)</td>\s*'
    r'<td[^>]*class="mgAlignRightCell"[^>]*>(\d+)</td>\s*'
    r'<td[^>]*class="mgAlignRightCell"[^>]*>[^<]*</td>\s*'
    r'<td[^>]*class="(?:mgMainTxtBold|mgTopText)"[^>]*>\s*(Elected|Not elected)\s*</td>',
    re.DOTALL | re.IGNORECASE,
)

COUNCIL_INDEX_LINK_RE = re.compile(
    r'<a[^>]+href="mgElectionAreaResults\.aspx\?[^"]*\bID=(\d+)[^"]*"[^>]+'
    r'title="Link to election area results for ([^"]+)"',
    re.IGNORECASE,
)

INCAPSULA_BOUNCE_RE = re.compile(
    rb'_Incapsula_Resource\?(SWUDNSAI|SWJIYLWA)|Request unsuccessful\. Incapsula incident'
)
FAILED_SENTINEL_PREFIX = b'<!-- gm-2026-ward-analysis: mycouncil fetch failed'


def _is_unusable_cache(content: bytes) -> bool:
    """Both Incapsula bounce pages and the 22-written failure sentinel
    are 'cache present but no data' — collapse them into one missing
    signal so the parser falls back to Wikipedia uniformly."""
    head = content[:2000]
    if content.startswith(FAILED_SENTINEL_PREFIX):
        return True
    return bool(INCAPSULA_BOUNCE_RE.search(head))


def parse_council_index(html: str) -> list[tuple[int, str]]:
    """Return [(area_id, ward_name), ...] from a mycouncil detailed-by-ward
    index page. The title='Link to ...' attribute carries the canonical
    ward name (with the " Ward" suffix moderngov adds — we strip it)."""
    out: list[tuple[int, str]] = []
    seen: set[int] = set()
    for m in COUNCIL_INDEX_LINK_RE.finditer(html):
        area_id = int(m.group(1))
        if area_id in seen:
            continue
        seen.add(area_id)
        name = html_lib.unescape(m.group(2)).strip()
        name = re.sub(r'\s+Ward$', '', name, flags=re.IGNORECASE).strip()
        out.append((area_id, name))
    return out


def parse_council_ward(html: str) -> tuple[dict[str, int], dict[str, int], list[dict]]:
    """Return (seats_won, votes_per_party, winners_list) for one
    mycouncil per-ward HTML. Multi-member: finditer over Elected +
    Not-elected rows."""
    seats: dict[str, int] = {}
    votes: dict[str, int] = {}
    winners: list[dict] = []
    for m in COUNCIL_ROW_RE.finditer(html):
        candidate = html_lib.unescape(m.group(1)).strip()
        party_raw = html_lib.unescape(m.group(2)).strip()
        v = int(m.group(3))
        outcome = m.group(4).lower()
        party = normalize_party(party_raw)
        votes[party] = votes.get(party, 0) + v
        if outcome == 'elected':
            seats[party] = seats.get(party, 0) + 1
            winners.append({
                'party': party,
                'candidate': candidate,
                'votes': v,
            })
    return seats, votes, winners


# ---------------------------------------------------------------------------
# Surrey CC electionmap parsing (cross-check only).
# ---------------------------------------------------------------------------

# Each elected candidate is one <tr> with five cells: party-swatch span,
# ward link, candidate name, party name, (sometimes a fifth). The ward
# link inside <a href="...mgElectionAreaResults.aspx?ID=<area_id>&EID=...">
# carries the ward name as link text — followed by " Ward".
ELECTIONMAP_ROW_RE = re.compile(
    r'<a[^>]+href="[^"]*mgElectionAreaResults\.aspx\?ID=(\d+)[^"]*"[^>]*>'
    r'([^<]+?)</a>\s*</td>\s*'
    r'<td[^>]*>([^<]+?)</td>\s*'
    r'<td[^>]*>([^<]+?)</td>',
    re.DOTALL | re.IGNORECASE,
)


def parse_electionmap(html: str) -> dict[int, list[tuple[str, str]]]:
    """Return {area_id: [(candidate, normalised_party), ...]} for every
    elected candidate listed on one unitary's electionmap page."""
    out: dict[int, list[tuple[str, str]]] = {}
    for m in ELECTIONMAP_ROW_RE.finditer(html):
        area_id = int(m.group(1))
        candidate = html_lib.unescape(m.group(3)).strip()
        party_raw = html_lib.unescape(m.group(4)).strip()
        out.setdefault(area_id, []).append((candidate, normalize_party(party_raw)))
    return out


# ---------------------------------------------------------------------------
# Ward-name normalisation for matching across sources (the three sources
# punctuate ward names slightly differently; collapse to a comparable form).
# ---------------------------------------------------------------------------

def _norm_name(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r'\s+ward$', '', s)
    s = re.sub(r"[·,/&\-']", ' ', s)
    s = re.sub(r'\band\b', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ---------------------------------------------------------------------------
# Per-unitary merge: pick the best source for each ward, cross-check it.
# ---------------------------------------------------------------------------

def _name_tokens(s: str) -> set[str]:
    # Split on whitespace and strip punctuation so "O'Donovan" matches
    # itself irrespective of source. Hyphens stay (double-barrelled names).
    return {re.sub(r"[^\w\-']", '', tok).lower() for tok in s.split() if tok}


def _names_compatible(a: str, b: str) -> bool:
    """True if a and b refer to the same person — one's token set must
    be a subset of the other's. Handles Wikipedia abbreviating middle
    names that Surrey CC's electionmap spells out in full (e.g. wiki
    'David Lewis' vs electionmap 'David John Lewis')."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    return ta.issubset(tb) or tb.issubset(ta)


def _crosscheck_winners(
    chosen: list[dict],
    electionmap: list[tuple[str, str]],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Return (chosen_extras, electionmap_extras) — winners on each side
    that don't have a compatible-name + same-party match on the other.
    Empty pair means the two sources agree."""
    chosen_pairs = [(w.get('candidate') or '', w['party']) for w in chosen]
    em_pairs = list(electionmap)
    em_remaining = em_pairs.copy()
    chosen_extras: set[tuple[str, str]] = set()
    for c_name, c_party in chosen_pairs:
        for j, (e_name, e_party) in enumerate(em_remaining):
            if e_party == c_party and _names_compatible(c_name, e_name):
                em_remaining.pop(j)
                break
        else:
            chosen_extras.add((c_name, c_party))
    return chosen_extras, set(em_remaining)


def merge_unitary(
    code: str, name: str, wiki_title: str,
    wiki_rows: list[tuple[str, dict, dict, list[dict]]],
    council_by_area: dict[int, tuple[dict, dict, list[dict]]],
    council_name_by_area: dict[int, str],
    electionmap: dict[int, list[tuple[str, str]]],
) -> tuple[list[dict], list[str], dict[str, int]]:
    """Return (output rows, disagreement messages, source counts).

    `council_by_area` is {area_id: (seats, votes, winners)} for whichever
    XSE/XSW ward pages were parsed successfully (bounced or missing
    caches are simply absent from this dict).
    """
    # Index the council and electionmap data by normalised ward name so
    # we can join from Wikipedia's ward-name keys.
    council_by_name: dict[str, tuple[int, dict, dict, list[dict]]] = {}
    for area_id, (seats, votes, winners) in council_by_area.items():
        cname = council_name_by_area.get(area_id)
        if not cname:
            continue
        council_by_name[_norm_name(cname)] = (area_id, seats, votes, winners)

    electionmap_by_name: dict[str, tuple[int, list[tuple[str, str]]]] = {}
    # The electionmap page lists each elected candidate once but doesn't
    # carry the ward name — we rejoin via area_id back to the mycouncil
    # index name for canonical labelling.
    for area_id, pairs in electionmap.items():
        ward_name = council_name_by_area.get(area_id)
        if not ward_name:
            continue
        electionmap_by_name[_norm_name(ward_name)] = (area_id, pairs)

    rows: list[dict] = []
    disagreements: list[str] = []
    src_counts: dict[str, int] = {
        'wiki': 0, 'council': 0, 'pending': 0,
        'em_checked': 0, 'em_matched': 0,
    }

    for ward_name, w_seats, w_votes, w_winners in wiki_rows:
        norm = _norm_name(ward_name)
        council_hit = council_by_name.get(norm)
        em_hit = electionmap_by_name.get(norm)

        # Choose the source. Prefer mycouncil if it has winners (richer
        # data — every candidate's votes); fall back to Wikipedia.
        if council_hit and council_hit[3]:
            area_id, c_seats, c_votes, c_winners = council_hit
            chosen_seats, chosen_votes, chosen_winners = c_seats, c_votes, c_winners
            source = f'surrey-cc:{area_id}'
            src_counts['council'] += 1
        elif w_winners:
            chosen_seats, chosen_votes, chosen_winners = w_seats, w_votes, w_winners
            source = f'wiki:{wiki_title}'
            src_counts['wiki'] += 1
        else:
            chosen_seats, chosen_votes, chosen_winners = w_seats, w_votes, w_winners
            source = f'wiki:{wiki_title}'
            src_counts['pending'] += 1

        # Cross-check against electionmap whenever we have data on both
        # sides. Wikipedia often abbreviates middle names that the
        # electionmap spells out — _crosscheck_winners tolerates that
        # via token-subset matching, so only real disagreements (a
        # different surname / different party) surface here.
        if em_hit and chosen_winners:
            src_counts['em_checked'] += 1
            chosen_extras, em_extras = _crosscheck_winners(
                chosen_winners, em_hit[1],
            )
            if chosen_extras or em_extras:
                disagreements.append(
                    f'  {code} :: {ward_name} (source={source}): '
                    f'chosen extras={sorted(chosen_extras)} '
                    f'electionmap extras={sorted(em_extras)}'
                )
            else:
                src_counts['em_matched'] += 1

        if chosen_seats:
            winner = max(
                chosen_seats.items(),
                key=lambda kv: (kv[1], chosen_votes.get(kv[0], 0)),
            )[0]
        else:
            winner = 'Pending'

        rows.append({
            'lad_code':  code,
            'lad_name':  name,
            'ward_code': f'{code}::{_slug(ward_name)}',
            'ward_name': ward_name,
            'winner':    winner,
            'seats_won': chosen_seats,
            'winners':   chosen_winners,
            'year':      2026,
            'votes':     chosen_votes,
            'source':    source,
        })

    wiki_norms = {_norm_name(r[0]) for r in wiki_rows}
    wiki_name_by_norm = {_norm_name(r[0]): r[0] for r in wiki_rows}
    council_index_norms = {_norm_name(n) for n in council_name_by_area.values()}

    unmatched_council = [
        (area_id, council_name_by_area[area_id])
        for norm, (area_id, _s, _v, winners) in council_by_name.items()
        if winners and norm not in wiki_norms
    ]
    if unmatched_council:
        print(
            f'  WARN {code}: {len(unmatched_council)} mycouncil ward(s) have '
            'results but no matching Wikipedia ward box — silently dropped '
            'from the output. Add a Wikipedia box (or extend _norm_name) to '
            'include them:', file=sys.stderr,
        )
        for area_id, ward_name in unmatched_council:
            print(f'    - area_id={area_id} :: {ward_name!r}', file=sys.stderr)

    # Wiki wards with no mycouncil match by normalised name. Wiki's row
    # still renders, but the source-preference logic can never pick
    # mycouncil and the electionmap cross-check is skipped — usually a
    # punctuation or singular/plural drift (today: XSE
    # 'Nork & Tattenham' vs mycouncil 'Nork & Tattenhams'). Guarded on
    # the index actually loading so we don't spam every wiki ward when
    # mycouncil is fully unavailable.
    if council_index_norms:
        unmatched_wiki = sorted(
            wiki_name_by_norm[norm]
            for norm in wiki_norms
            if norm not in council_index_norms
        )
        if unmatched_wiki:
            print(
                f'  WARN {code}: {len(unmatched_wiki)} Wikipedia ward(s) '
                'have no matching mycouncil ward by normalised name — '
                'electionmap cross-check skipped for these:',
                file=sys.stderr,
            )
            for ward_name in unmatched_wiki:
                print(f'    - {ward_name!r}', file=sys.stderr)

    return rows, disagreements, src_counts


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _load_council_index(eid: int) -> dict[int, str]:
    path = SOURCE / f'surrey_council_index_{eid}.html'
    if not path.exists():
        return {}
    if _is_unusable_cache(path.read_bytes()):
        print(f'  ! mycouncil index EID={eid} is an Incapsula bounce or '
              'failure sentinel; mycouncil data for this unitary '
              'unavailable.', file=sys.stderr)
        return {}
    pairs = parse_council_index(path.read_text('utf-8', errors='replace'))
    return {area_id: name for area_id, name in pairs}


def _load_council_ward(area_id: int) -> tuple[dict, dict, list[dict]] | None:
    path = SOURCE / f'surrey_council_ward_{area_id}.html'
    if not path.exists() or _is_unusable_cache(path.read_bytes()):
        return None
    return parse_council_ward(path.read_text('utf-8', errors='replace'))


def _load_electionmap(code: str) -> dict[int, list[tuple[str, str]]]:
    path = SOURCE / f'surrey_electionmap_{code}.html'
    if not path.exists() or _is_unusable_cache(path.read_bytes()):
        return {}
    return parse_electionmap(path.read_text('utf-8', errors='replace'))


def main():
    all_rows: list[dict] = []
    summary_lines: list[str] = []
    disagreements: list[str] = []

    for code, name, wiki_title, _districts in SURREY_UNITARIES:
        # 1. Wikipedia.
        wiki_slug = re.sub(r'[^a-z0-9]+', '_', wiki_title.lower()).strip('_')
        wiki_path = SOURCE / f'wiki_surrey_{wiki_slug}_2026.json'
        if not wiki_path.exists():
            print(f'  ! {code} {name}: missing wiki cache {wiki_path.name}',
                  file=sys.stderr)
            continue
        wt = json.loads(wiki_path.read_text())['parse']['wikitext']
        wiki_rows = parse_wikipedia(wt)

        # 2. mycouncil per-ward results (only the ones with a good cache).
        # Map area_id → canonical ward name via the index page.
        idx_url = SURREY_COUNCIL_INDEX_URLS[code]
        eid = int(re.search(r'EID=(\d+)', idx_url).group(1))

        council_name_by_area = _load_council_index(eid)
        council_by_area: dict[int, tuple[dict, dict, list[dict]]] = {}
        for area_id in council_name_by_area:
            parsed = _load_council_ward(area_id)
            if parsed is not None:
                council_by_area[area_id] = parsed

        # 3. Electionmap cross-check.
        electionmap = _load_electionmap(code)

        rows, unit_disagreements, src_counts = merge_unitary(
            code, name, wiki_title,
            wiki_rows, council_by_area,
            council_name_by_area, electionmap,
        )
        all_rows.extend(rows)
        disagreements.extend(unit_disagreements)

        decided = sum(1 for r in rows if r['seats_won'])
        total_seats = sum(sum(r['seats_won'].values()) for r in rows)
        expected_seats = len(rows) * 2
        summary_lines.append(
            f'{code} {name:<12} {len(rows):>2} wards · '
            f'{src_counts["wiki"]:>2} from Wikipedia · '
            f'{src_counts["council"]:>2} from Surrey CC · '
            f'{decided:>2} decided · {total_seats:>3}/{expected_seats} seats · '
            f'electionmap cross-check '
            f'{src_counts["em_matched"]}/{src_counts["em_checked"]} '
            f'(of {len(electionmap)} on electionmap)'
        )

    print('\n'.join(summary_lines))

    pending = [r for r in all_rows if not r['seats_won']]
    if pending:
        print(
            f'\n  WARN {len(pending)} ward(s) still have no winner '
            '(neither Wikipedia nor Surrey CC have published results):',
            file=sys.stderr,
        )
        for r in pending:
            print(f'    - {r["lad_code"]}::{r["ward_name"]}', file=sys.stderr)
        print(
            '  These render as Pending (grey). Re-run 22 to retry the '
            'Surrey CC fetch; the issue likely resolves once Incapsula '
            'lets the requests through.', file=sys.stderr,
        )

    if disagreements:
        print(
            f'\n  ERROR {len(disagreements)} ward(s) disagree with the '
            'Surrey CC electionmap cross-check. Refusing to overwrite '
            f'{OUT.relative_to(ROOT)} — investigate before committing, '
            'the rendered map would be wrong.', file=sys.stderr,
        )
        for d in disagreements:
            print(d, file=sys.stderr)
        sys.exit(1)

    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2))

    n_xse = sum(1 for r in all_rows if r['lad_code'] == 'XSE')
    n_xsw = sum(1 for r in all_rows if r['lad_code'] == 'XSW')
    print(
        f'\nSaved {OUT.relative_to(ROOT)} — '
        f'{len(all_rows)} wards ({n_xse} XSE + {n_xsw} XSW)'
    )


if __name__ == '__main__':
    main()
