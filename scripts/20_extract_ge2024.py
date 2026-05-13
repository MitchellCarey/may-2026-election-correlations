"""Parse cached Wikipedia wikitext for each PCON_JUL_2024 constituency into
a per-constituency record for the 4 July 2024 General Election, and emit
data/ge2024.json.

Reads:  data/source/wiki_ge2024_<slug>.json   (one per article, written by 19)
Writes: data/ge2024.json

Output schema — one record per PCON:

    {
      "code":         "E14001063",
      "name":         "Aldershot",
      "winner_party": "Labour",
      "candidate":    "Alex Baker",
      "year":         2024,
      "votes":        {"Labour": 19764, "Conservative": 14081, ...}
    }

Each Westminster constituency article carries one or more
{{Election box begin|title=[[<year> United Kingdom general election|...]]:}}
sections under H2 "Elections". We anchor on the 2024 block specifically,
read the winning candidate's party + name, then sum votes across the
remaining {{Election box candidate ...}} templates inside the same block
(closed by {{Election box end}}).

Party normalisation goes through _wiki_parser.normalize_party() with an
additional pass that preserves "Speaker" (Lindsay Hoyle's GE party label,
Chorley) rather than collapsing it to "Other". NI parties (DUP, Sinn Féin,
SDLP, UUP, Alliance, TUV) are not normalised — they fall through to "Other"
because the 18 NI seats are filtered out at render time in 07d regardless
of their party attribution. If NI rendering is ever turned on, the normaliser
would need extending.
"""
import json
import re
import sys
from pathlib import Path

from _ge2024_constituencies import GE2024_CONSTITUENCIES
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "ge2024.json"

# NI prefix gets dropped from the "GB total" but the records are still emitted
# (so 07d's GB filter is the single source of truth, and a future NI render
# needs no re-extract).
GB_PREFIXES = ('E14', 'W07', 'S14')

# {{Election box begin ... |title=[[<wikilink target containing 2024 and
# general election>|<label>]]}}
# Whitespace, bar placement, and the wikilink target shape vary across
# articles. Aldershot uses `[[2024 United Kingdom general election|...]]`,
# Holborn drops the optional empty positional `|<newline>|`, South West
# Norfolk uses `[[South West Norfolk in the 2024 United Kingdom general
# election|...]]`, Belfast North uses `[[2024 United Kingdom general
# election in Northern Ireland|...]]`. The anchor accepts anything inside
# the wikilink target so long as it contains both "2024" and "general
# election" — distinct enough to disambiguate from older general-election
# boxes in the same article.
ELECTION_BOX_2024_RE = re.compile(
    r'\{\{\s*Election box begin\b'
    r'[^}]*?'
    r'\|\s*title\s*=\s*\[\[[^\]|]*?2024[^\]|]*?general\s+election',
    re.IGNORECASE | re.DOTALL,
)
ELECTION_BOX_END_RE = re.compile(r'\{\{\s*Election box end\s*\}\}', re.IGNORECASE)

# Winner template — single per box, "with party link" suffix optional.
# `\s+` (not literal space) between word tokens because some articles
# (Spen Valley, …) use double spaces or wrap "winning" / "candidate"
# onto separate lines.
#
# Field captures are greedy `(?:\[\[[^\]]*\]\]|[^|}\n])+` rather than
# `[^|}\n]+` so a piped wikilink `[[Alex Baker (politician)|Alex Baker]]`
# is consumed whole — the inner `|` is the wikilink display separator,
# not a template-parameter delimiter, and the plain negative-char class
# would truncate the value at it. Non-greedy + a bridge gives the wrong
# answer for the opposite reason (party shrinks to empty and the bridge
# swallows "Labour Party (UK)"), so the captures stay greedy.
_FIELD_VALUE = r'(?:\[\[[^\]]*\]\]|[^|}\n])+'

WINNER_RE = re.compile(
    r'\{\{\s*Election\s+box\s+winning\s+candidate(?:\s+with\s+party\s+link)?'
    r'(?:[^{}]|\{\{[^{}]*\}\})*?'
    r'\|\s*party\s*=\s*(' + _FIELD_VALUE + r')'
    r'(?:[^{}]|\{\{[^{}]*\}\})*?'
    r'\|\s*candidate\s*=\s*(' + _FIELD_VALUE + r')',
    re.IGNORECASE | re.DOTALL,
)

# Candidate template — any candidate (winner or runner-up). Captures party
# + votes. The `votes=` value can contain commas; we strip non-digits.
CANDIDATE_RE = re.compile(
    r'\{\{\s*Election\s+box\s+(?:winning\s+)?candidate(?:\s+with\s+party\s+link)?'
    r'(?:[^{}]|\{\{[^{}]*\}\})*?'
    r'\|\s*party\s*=\s*(' + _FIELD_VALUE + r')'
    r'(?:[^{}]|\{\{[^{}]*\}\})*?'
    r'\|\s*votes\s*=\s*([\d,]+)',
    re.IGNORECASE | re.DOTALL,
)

# Strip [[Wikilink|Display]] → "Display" or [[Bare]] → "Bare".
WIKILINK_RE = re.compile(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]')


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def clean_candidate(name: str) -> str:
    """Wikipedia candidate fields commonly wrap the name in a wikilink and may
    have trailing whitespace, refs, or {{small}} qualifiers — collapse to a
    plain string."""
    s = WIKILINK_RE.sub(r'\1', name)
    s = re.sub(r'<ref\b[^>]*?/>', '', s, flags=re.IGNORECASE)
    s = re.sub(r'<ref\b[^>]*>.*?</ref>', '', s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r'\{\{[^{}]+\}\}', '', s)
    return s.strip()


def westminster_party(raw: str) -> str:
    """Normalise a Wikipedia `party=` field to one of the canonical labels.
    Preserves "Speaker" (Lindsay Hoyle, Chorley); everything else falls
    through to _wiki_parser.normalize_party which handles the major parties.
    NI parties (DUP, Sinn Féin, SDLP, UUP, Alliance, TUV) hit the "Other"
    bucket; that's fine because 07d filters NI seats out at render time."""
    s = raw.strip().lower().replace('[[', '').replace(']]', '')
    if '|' in s:
        s = s.split('|', 1)[-1].strip()
    # "Speaker of the House of Commons" / plain "Speaker" — keep distinct.
    if 'speaker' in s:
        return 'Speaker'
    return normalize_party(raw)


def parse_constituency(wt: str, name: str) -> dict | None:
    """Return the extracted record for one PCON, or None if no 2024 GE box
    can be located in the article wikitext."""
    box = ELECTION_BOX_2024_RE.search(wt)
    if not box:
        return None
    block_start = box.start()
    end = ELECTION_BOX_END_RE.search(wt, block_start)
    block_end = end.end() if end else len(wt)
    block = wt[block_start:block_end]

    win = WINNER_RE.search(block)
    if not win:
        return None
    winner_party = westminster_party(win.group(1))
    candidate = clean_candidate(win.group(2))

    votes: dict[str, int] = {}
    for m in CANDIDATE_RE.finditer(block):
        p = westminster_party(m.group(1))
        v = int(m.group(2).replace(',', ''))
        votes[p] = votes.get(p, 0) + v

    return {
        'winner_party': winner_party,
        'candidate':    candidate,
        'year':         2024,
        'votes':        votes,
    }


def main():
    records = []
    misses: list[tuple[str, str]] = []
    missing_cache: list[tuple[str, str]] = []

    for code, name, title in GE2024_CONSTITUENCIES:
        path = SOURCE / f'wiki_ge2024_{slug(title)}.json'
        if not path.exists():
            missing_cache.append((code, name))
            continue
        with open(path) as f:
            wt = json.load(f)['parse']['wikitext']

        record = parse_constituency(wt, name)
        if record is None:
            misses.append((code, name))
            records.append({
                'code':         code,
                'name':         name,
                'winner_party': None,
                'candidate':    None,
                'year':         2024,
                'votes':        {},
            })
            continue
        records.append({'code': code, 'name': name, **record})

    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False))

    gb_records = [r for r in records if r['code'].startswith(GB_PREFIXES)]
    gb_with_winner = [r for r in gb_records if r['winner_party']]
    ni_records = [r for r in records if r['code'].startswith('N05')]

    print(f'\nSaved {OUT.relative_to(ROOT)} — '
          f'{len(gb_with_winner)}/{len(gb_records)} GB constituencies '
          f'({len(records)}/650 fetched, {len(ni_records)} NI deferred)')

    # Per-party tally across GB only — the user-facing diagnostic.
    from collections import Counter
    parties = Counter(r['winner_party'] for r in gb_with_winner if r['winner_party'])
    print('  GB winners by party:', ', '.join(
        f'{p} {n}' for p, n in parties.most_common()
    ))

    if missing_cache:
        print(f'  WARN: {len(missing_cache)} cache files missing — re-run '
              f'scripts/19_fetch_ge2024_results.py', file=sys.stderr)
        for code, name in missing_cache[:5]:
            print(f'    {code} {name}', file=sys.stderr)
    # Split misses into GB (real failures, need investigation) and NI
    # (expected: 07d filters NI out at render time regardless).
    gb_misses = [m for m in misses if m[0].startswith(GB_PREFIXES)]
    ni_misses = [m for m in misses if m[0].startswith('N05')]
    if gb_misses:
        print(f'  WARN: {len(gb_misses)} GB articles have no 2024 GE '
              f'Election box (anchor regex missed):', file=sys.stderr)
        for code, name in gb_misses:
            print(f'    {code} {name}', file=sys.stderr)
    if ni_misses:
        print(f'  (info: {len(ni_misses)} NI seats parsed as deferred — '
              f'NI uses a hold/gain template style that the FPTP parser '
              f'skips, but these get filtered out at render time anyway.)',
              file=sys.stderr)


if __name__ == '__main__':
    main()
