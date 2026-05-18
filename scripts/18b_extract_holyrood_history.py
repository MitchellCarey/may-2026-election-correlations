"""Parse the 73 cached per-constituency Wikipedia articles fetched by
scripts/17b_fetch_holyrood_history.py and emit one record per
(constituency, year) for the 2016 and 2021 Holyrood elections.

Per-constituency articles use the **AMS election box** template family
(Additional Member System — Holyrood's hybrid FPTP-plus-regional-list voting):

  {{AMS election box begin |title=[[YYYY Scottish Parliament election]]: <Name>...}}
  {{AMS election box with party link
    |party     = Scottish National Party
    |candidate = [[Kevin Stewart...]]
    |votes     = 10,058
    |winner    = yes
  }}
  ... other candidates without winner=yes ...
  {{AMS election box turnout ...}}
  {{AMS election box win|winner = SNP}}   OR   {{AMS election box hold|winner=...}}
  {{AMS election box end|notes=yes}}

The parser walks each `AMS election box begin ... end` block, captures the
year from the title, and extracts the winner by:
  1. preferring the candidate row marked `|winner = yes`
  2. falling back to the `AMS election box {win,hold,gain}` template's
     `winner = ...` parameter
The candidate name is captured for the tooltip.

Output: data/holyrood_history_raw.json — flat list of records:
  {"spc22cd": "S16000074", "name": "Aberdeen Central",
   "year": 2021, "winner": "SNP", "candidate": "Kevin Stewart",
   "source": "wiki", "url": "https://en.wikipedia.org/wiki/..."}

Years emitted: only 2016 and 2021 (Phase 1C's SLIDER_YEARS). The articles
carry pre-2011 contests too but those would only be useful for a later
Phase 1F (depth: 2010/2011) — not in scope here.

Coverage target: 73/73 at both 2021 and 2016. The script prints a per-year
summary and surfaces any missing-year matches on stderr (per the "surface
silent join failures" rule).
"""
import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _holyrood_constituencies import HOLYROOD_22
from _wiki_parser import normalize_party

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "holyrood_history_raw.json"

TARGET_YEARS = (2016, 2021)

# Match the opening of an AMS election box block; capture position only.
# (Some articles use plain `{{Election box begin}}` for pre-2007 contests —
# we don't need those for Phase 1C, so we filter on AMS only.)
AMS_BEGIN_RE = re.compile(r'\{\{\s*AMS\s+election\s+box\s+begin\b', re.IGNORECASE)
AMS_END_RE = re.compile(r'\{\{\s*AMS\s+election\s+box\s+end[^}]*\}\}', re.IGNORECASE)

# Year captured from `title = [[YYYY Scottish Parliament election]]: ...`.
TITLE_YEAR_RE = re.compile(
    r'title\s*=\s*\[\[\s*(\d{4})\s+Scottish\s+Parliament\s+election',
    re.IGNORECASE,
)

# Opening marker for a candidate row — body extraction below is brace-aware
# because rows contain nested templates like `{{increase}}1.7` whose `}}`
# would otherwise terminate a naive `(.*?)\}\}` match prematurely.
CANDIDATE_OPEN_RE = re.compile(
    r'\{\{\s*AMS\s+election\s+box\s+with(?:\s+list)?\s+party\s+link\b',
    re.IGNORECASE,
)


def iter_candidate_bodies(block_text: str):
    """Yield the body of each `AMS election box with [list] party link` template
    in `block_text`, scanning brace-balanced so nested `{{increase}}` etc. don't
    truncate the row. Body excludes the opening template name."""
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
# internal `|` of disambiguated forms like `[[Kevin Stewart (Scottish
# politician)|Kevin Stewart]]` doesn't truncate the value) or a single
# non-terminating character. Without the wikilink alternation the capture
# stops at the first `|` and `clean_candidate`'s `[[Foo|Bar]]` cleanup
# regex (which requires the closing `]]`) leaves the broken link verbatim.
PARTY_PARAM_RE  = re.compile(
    r'\|\s*party\s*=\s*((?:\[\[[^\]]*\]\]|[^\n|}])+)',
    re.IGNORECASE,
)
CANDIDATE_PARAM_RE = re.compile(
    r'\|\s*candidate\s*=\s*((?:\[\[[^\]]*\]\]|[^\n|}])+)',
    re.IGNORECASE,
)
WINNER_PARAM_RE = re.compile(r'\|\s*winner\s*=\s*yes\b', re.IGNORECASE)

# Tail templates that record the win for AMS-formatted articles.
TAIL_WIN_RE = re.compile(
    r'\{\{\s*AMS\s+election\s+box\s+(?:win|hold|gain)\b[^}]*?\|\s*winner\s*=\s*([^\n|}]+)',
    re.IGNORECASE | re.DOTALL,
)


def clean_candidate(raw: str) -> str:
    """Strip wikilink wrapping + parenthesised disambiguators from a
    `candidate = ...` value. Tolerant of trailing refs/HTML noise."""
    s = raw.strip()
    s = re.sub(r'<ref.*?(?:/>|</ref>)', '', s, flags=re.DOTALL)
    # [[Foo|Bar]] → Bar; [[Foo]] → Foo
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
    marker first, then the tail `AMS election box {win,hold,gain}` template."""
    for body in iter_candidate_bodies(block_text):
        if not WINNER_PARAM_RE.search(body):
            continue
        pm = PARTY_PARAM_RE.search(body)
        cm = CANDIDATE_PARAM_RE.search(body)
        if pm:
            return pm.group(1).strip(), clean_candidate(cm.group(1)) if cm else None

    # Fallback: tail template carries `winner=<party>`.
    tail = TAIL_WIN_RE.search(block_text)
    if tail:
        return tail.group(1).strip(), None

    return None, None


def wiki_url(title: str) -> str:
    """Same convention as 04d / 04e."""
    return f'https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(" ", "_"), safe="_,()/")}'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.parse_args()

    records: list[dict] = []
    misses_by_year: dict[int, list[str]] = {y: [] for y in TARGET_YEARS}
    matches_by_year: dict[int, int] = {y: 0 for y in TARGET_YEARS}

    for spc22cd, name, _region, wiki_title in HOLYROOD_22:
        path = SOURCE / f'wiki_holyrood_constituency_{spc22cd}.json'
        if not path.exists():
            print(f'  WARN: {path.relative_to(ROOT)} not cached — '
                  f'run scripts/17b first.', file=sys.stderr)
            continue
        raw = json.loads(path.read_text())
        wt = raw.get('parse', {}).get('wikitext', '')
        url = wiki_url(wiki_title)

        # Index AMS blocks by year so each TARGET_YEARS lookup is O(1).
        blocks_by_year: dict[int, str] = {}
        for s, e in find_blocks(wt):
            block_text = wt[s:e]
            ym = TITLE_YEAR_RE.search(block_text[:600])  # title is in the leading template
            if not ym:
                continue
            year = int(ym.group(1))
            blocks_by_year.setdefault(year, block_text)  # first-write-wins per year

        for year in TARGET_YEARS:
            block = blocks_by_year.get(year)
            if not block:
                misses_by_year[year].append(f'{spc22cd} · {name}')
                continue
            party_raw, candidate = extract_winner(block)
            if not party_raw:
                misses_by_year[year].append(f'{spc22cd} · {name} (no winner row)')
                continue
            party = normalize_party(party_raw)
            records.append({
                'spc22cd':   spc22cd,
                'name':      name,
                'year':      year,
                'winner':    party,
                'candidate': candidate,
                'source':    'wiki',
                'url':       url,
            })
            matches_by_year[year] += 1

    records.sort(key=lambda r: (r['year'], r['spc22cd']))
    OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False))

    total = len(HOLYROOD_22)
    print(f'\nWrote {OUT.relative_to(ROOT)}: {len(records)} records '
          f'({len(records)/2:.0f} avg per year)')
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
