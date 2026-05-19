"""Parse the 40 cached per-constituency Wikipedia articles fetched by
scripts/14b_fetch_senedd_history.py and emit one record per (constituency,
year) for the 2016 and 2021 Senedd / National Assembly for Wales
constituency contests (issue #69 Phase 1D / #72).

Welsh constituency articles use the same `{{AMS election box ...}}`
template family as Scottish ones (Wales also runs Additional Member
System — FPTP constituency vote + regional list vote on the same
ballot). Per-contest blocks have the shape:

  {{AMS election box begin |title=[[YYYY Senedd election]]: <Name>...}}
  {{AMS election box with party link
    |party        = Welsh Labour
    |candidate    = [[David Rees (politician)|David Rees]]
    |votes        = 10,505
    ...
    |winner       = yes
  }}
  ... other candidate rows ...
  {{Election box hold with party link |winner = Welsh Labour }}
  {{AMS election box end|notes=yes}}

The 2016 contests use `[[YYYY National Assembly for Wales election]]` in
the title (pre-rename), 2021 uses `[[YYYY Senedd election]]`. Both are
recognised. (Some articles also link 2003/2007/2011 contests under the
"Welsh Assembly election" wording — also recognised, though out of the
SLIDER_YEARS window for Phase 1D.)

Winner detection mirrors 18b:
  1. Prefer the candidate row marked `|winner = yes`.
  2. Fall back to the tail `{{Election box {hold,gain} with party link
     |winner = ...}}` template (Welsh tail template differs from
     Holyrood's `{{AMS election box win|hold|gain}}`).

Output: data/senedd_history_raw.json — flat list of records:
  {"nawc21cd": "W09000022", "name": "Aberavon",
   "year": 2021, "winner": "Labour", "candidate": "David Rees",
   "source": "wiki", "url": "https://en.wikipedia.org/wiki/...",
   "kind": "fptp"}

The `kind` field reserves space for commit 3's regional-list records
(kind: "regional") so 04g can downstream-sort by kind.

Coverage target: 40/40 at both 2016 and 2021. Misses are surfaced to
stderr per the "WARN on silent join failures" rule.
"""
import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _senedd_constituencies_2007 import SENEDD_CONSTITUENCIES_2007
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "senedd_history_raw.json"

TARGET_YEARS = (2016, 2021)

AMS_BEGIN_RE = re.compile(r'\{\{\s*AMS\s+election\s+box\s+begin\b', re.IGNORECASE)
# The 2021 box closes with `{{AMS election box end|notes=yes}}` but the
# pre-2021 contests (2003 / 2007 / 2011 / 2016) close with plain
# `{{Election box end}}`. Accept either — the alternation also handles
# any future contest that uses the AMS-prefixed form.
AMS_END_RE = re.compile(
    r'\{\{\s*(?:AMS\s+)?Election\s+box\s+end\b[^}]*\}\}',
    re.IGNORECASE,
)

# Year captured from `title = [[YYYY {Senedd|Welsh Assembly|National
# Assembly for Wales} election]]: ...`. The body politic was renamed
# May 2020, so 2016 articles say "National Assembly for Wales" and 2021
# articles say "Senedd". Some older boxes use "Welsh Assembly election"
# as a redirect-anchored link form.
TITLE_YEAR_RE = re.compile(
    r'title\s*=\s*\[\[\s*(\d{4})\s+'
    r'(?:Senedd|Welsh\s+Assembly|National\s+Assembly\s+for\s+Wales)\s+election',
    re.IGNORECASE,
)

# Opening marker for a candidate row. Welsh articles use two variants:
#   {{AMS election box with party link ...}}            — partied candidates
#   {{AMS election box with constituency party link ...}} — independents on the
#                                                            constituency vote only
# (There's also `with list party link` for list-only entries — those never
# carry `winner = yes` for the constituency ballot, so ignoring them is fine.)
CANDIDATE_OPEN_RE = re.compile(
    r'\{\{\s*AMS\s+election\s+box\s+with\s+'
    r'(?:constituency\s+)?party\s+link\b',
    re.IGNORECASE,
)


def iter_candidate_bodies(block_text: str):
    """Yield the body of each AMS candidate-row template in `block_text`,
    scanning brace-balanced so nested `{{increase}}` etc. don't truncate
    the row. Body excludes the opening template name."""
    for m in CANDIDATE_OPEN_RE.finditer(block_text):
        i = m.end()
        depth = 1
        n = len(block_text)
        while i < n - 1 and depth > 0:
            if block_text[i] == '{' and block_text[i + 1] == '{':
                depth += 1
                i += 2
            elif block_text[i] == '}' and block_text[i + 1] == '}':
                depth -= 1
                if depth == 0:
                    yield block_text[m.end():i]
                    i += 2
                    break
                i += 2
            else:
                i += 1


# The value captures consume either a complete `[[...]]` wikilink (so the
# internal `|` of disambiguated forms doesn't truncate the value) or a
# single non-terminating character. Mirrors 18b's PARTY/CANDIDATE patterns.
PARTY_PARAM_RE = re.compile(
    r'\|\s*party\s*=\s*((?:\[\[[^\]]*\]\]|[^\n|}])+)',
    re.IGNORECASE,
)
CANDIDATE_PARAM_RE = re.compile(
    r'\|\s*candidate\s*=\s*((?:\[\[[^\]]*\]\]|[^\n|}])+)',
    re.IGNORECASE,
)
WINNER_PARAM_RE = re.compile(r'\|\s*winner\s*=\s*yes\b', re.IGNORECASE)

# Tail template for Welsh constituencies — `{{Election box {hold,gain}
# with party link |winner = Welsh Labour }}`. Note the "with party link"
# suffix (Holyrood's tail is `{{AMS election box {win,hold,gain}}}`
# without the suffix).
TAIL_WIN_RE = re.compile(
    r'\{\{\s*Election\s+box\s+(?:hold|gain)\s+with\s+party\s+link\b'
    r'[^}]*?\|\s*winner\s*=\s*([^\n|}]+)',
    re.IGNORECASE | re.DOTALL,
)


def clean_candidate(raw: str) -> str:
    """Strip wikilink wrapping from a `candidate = ...` value, preferring
    the display label of a piped wikilink. Mirrors 18b."""
    s = raw.strip()
    s = re.sub(r'<ref.*?(?:/>|</ref>)', '', s, flags=re.DOTALL)
    m = re.search(r'\[\[([^\]\|]+?)(?:\|([^\]]+))?\]\]', s)
    if m:
        s = (m.group(2) or m.group(1)).strip()
    s = re.sub(r"'''", '', s)
    return s.strip(" '")


def find_blocks(wt: str) -> list[tuple[int, int]]:
    """Return (start, end) spans for every AMS election box block. The end
    is the position *after* the closing `{{AMS election box end...}}`."""
    spans = []
    for begin in AMS_BEGIN_RE.finditer(wt):
        end_m = AMS_END_RE.search(wt, begin.end())
        if not end_m:
            continue
        spans.append((begin.start(), end_m.end()))
    return spans


def extract_winner(block_text: str) -> tuple[str | None, str | None]:
    """Walk a single AMS block and return (party_raw, candidate_raw) for the
    winner, or (None, None) if not found. Tries the row-level `winner=yes`
    marker first, then the tail `Election box {hold,gain} with party link`."""
    for body in iter_candidate_bodies(block_text):
        if not WINNER_PARAM_RE.search(body):
            continue
        pm = PARTY_PARAM_RE.search(body)
        cm = CANDIDATE_PARAM_RE.search(body)
        if pm:
            return pm.group(1).strip(), clean_candidate(cm.group(1)) if cm else None

    tail = TAIL_WIN_RE.search(block_text)
    if tail:
        return tail.group(1).strip(), None

    return None, None


def wiki_url(title: str) -> str:
    return f'https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(" ", "_"), safe="_,()/")}'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.parse_args()

    records: list[dict] = []
    misses_by_year: dict[int, list[str]] = {y: [] for y in TARGET_YEARS}
    matches_by_year: dict[int, int] = {y: 0 for y in TARGET_YEARS}

    for nawc21cd, name, wiki_title, _region in SENEDD_CONSTITUENCIES_2007:
        path = SOURCE / f'wiki_senedd_constituency_{nawc21cd}.json'
        if not path.exists():
            print(f'  WARN: {path.relative_to(ROOT)} not cached — '
                  f'run scripts/14b first.', file=sys.stderr)
            continue
        raw = json.loads(path.read_text())
        wt = raw.get('parse', {}).get('wikitext', '')
        url = wiki_url(wiki_title)

        # Index AMS blocks by year so each TARGET_YEARS lookup is O(1).
        blocks_by_year: dict[int, str] = {}
        for s, e in find_blocks(wt):
            block_text = wt[s:e]
            ym = TITLE_YEAR_RE.search(block_text[:600])
            if not ym:
                continue
            year = int(ym.group(1))
            blocks_by_year.setdefault(year, block_text)  # first-write-wins per year

        for year in TARGET_YEARS:
            block = blocks_by_year.get(year)
            if not block:
                misses_by_year[year].append(f'{nawc21cd} · {name}')
                continue
            party_raw, candidate = extract_winner(block)
            if not party_raw:
                misses_by_year[year].append(f'{nawc21cd} · {name} (no winner row)')
                continue
            party = normalize_party(party_raw)
            records.append({
                'nawc21cd':  nawc21cd,
                'name':      name,
                'year':      year,
                'winner':    party,
                'candidate': candidate,
                'source':    'wiki',
                'url':       url,
                'kind':      'fptp',
            })
            matches_by_year[year] += 1

    records.sort(key=lambda r: (r['kind'], r['year'], r['nawc21cd']))
    OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False))

    total = len(SENEDD_CONSTITUENCIES_2007)
    print(f'\nWrote {OUT.relative_to(ROOT)}: {len(records)} records '
          f'({len(records)/len(TARGET_YEARS):.0f} avg per year)')
    for y in TARGET_YEARS:
        ok = matches_by_year[y]
        miss = len(misses_by_year[y])
        print(f'  {y}: {ok}/{total} matched · {miss} unmatched')

    for y in TARGET_YEARS:
        if misses_by_year[y]:
            print(f'\n  WARN: {y} unmatched ({len(misses_by_year[y])}):', file=sys.stderr)
            for m in misses_by_year[y]:
                print(f'    {m}', file=sys.stderr)


if __name__ == '__main__':
    main()
