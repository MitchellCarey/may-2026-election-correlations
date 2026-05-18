"""One-off helper to expand `wiki_current_articles` in councils.yaml back
to 2018 so the time slider (issue #70 / #69 phase 1A) has data for every
ward at every contest year between 2018 and 2026.

Not invoked by the pipeline. Leading underscore by convention.

Algorithm: text-based block editor. For each council block (delimited by
flush-left `- lad_code:` markers), parse out the canonical title pattern
(from wiki_2026 / wiki_prior / existing wiki_current_articles), compute
which historical years are missing, and rewrite the council's
`wiki_current_articles:` field as either a freshly populated list or an
extended one. ruamel.yaml-style indent (2/4/2) is preserved for new
entries to match the file's existing aesthetic.

Why text manipulation and not a YAML library: PyYAML strips comments;
ruamel.yaml's round-tripper re-indents top-level sequences in a way that
churns every council in the file. The change set we need is purely additive
to a single field — text editing produces a minimal, reviewable diff.

After running, follow up with:
    .venv/bin/python scripts/10_fetch_current_winners.py
to pull the new articles. The fetcher logs 404s; audit them and either:
  - remove the bad entry from YAML (council didn't exist that year /
    boundary review suspended the election), or
  - add the (council_name, year) → title pair to TITLE_OVERRIDES below
    and re-run.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COUNCILS = ROOT / 'data' / 'source' / 'councils.yaml'

# Candidate contest years per cycle. 2020 deferred to 2021 in England under
# the Local Government and Police and Crime Commissioner (Coronavirus)
# (Postponement of Elections and Referendums) (England and Wales)
# Regulations 2020, so no 2020 entries are useful.
THIRDS_YEARS = [2018, 2019, 2021, 2022, 2023, 2024, 2025]
HALVES_YEARS = [2018, 2021, 2022, 2024]

# Per-(name, year) title overrides — councils whose Wikipedia article title
# for one year differs from the canonical "<year> <pattern> election" form.
# Populate via the misses list printed by scripts/10 and re-run this script.
TITLE_OVERRIDES: dict[tuple[str, int], str] = {
    # ("Wolverhampton", 2018): "2018 City of Wolverhampton Council election",
}

# Councils that didn't exist (under their LAD24 code) until the given year.
# Don't synthesise pre-existence entries for these. Existing entries always
# preserved regardless.
COUNCIL_FOUNDED: dict[str, int] = {
    "E06000058": 2019,  # Bournemouth, Christchurch and Poole
    "E06000059": 2019,  # Dorset
    "E07000244": 2019,  # East Suffolk
    "E07000245": 2019,  # West Suffolk
    "E07000246": 2019,  # Somerset West and Taunton
    "E06000060": 2021,  # Buckinghamshire (became unitary 2020, first election 2021)
    "E06000061": 2021,  # North Northamptonshire
    "E06000062": 2021,  # West Northamptonshire
    "E06000063": 2023,  # Cumberland
    "E06000064": 2023,  # Westmorland and Furness
    "E06000065": 2023,  # North Yorkshire (unitary)
    "E06000066": 2023,  # Somerset (unitary)
}

GB_PREFIXES = ('E06', 'E07', 'E08', 'E09', 'W06', 'S12')

TITLE_RE = re.compile(r'^(\d{4}) (.+) election$')


def parse_council_block(block: str) -> dict:
    """Extract fields we care about from a council block (the lines between
    one `- lad_code:` marker and the next)."""
    fields: dict[str, str] = {}
    # First line uses `- lad_code: …`; subsequent lines use `  <field>: …`.
    for m in re.finditer(r'^(?:- |  )([a-z_0-9]+):[ \t]*(.*)$', block, re.MULTILINE):
        fields[m.group(1)] = m.group(2).strip()
    # Pull existing wiki_current_articles entries if present.
    existing_years: set[int] = set()
    existing_titles: list[tuple[int, str]] = []
    # Look for the wiki_current_articles section — either `null` on the same
    # line, or an empty value followed by a child list. Use `[ \t]*` (not
    # `\s*`) so we don't accidentally gobble newlines and pick up the first
    # list item's text as the value.
    wc_match = re.search(
        r'^  wiki_current_articles:[ \t]*(.*)$',
        block, re.MULTILINE
    )
    if wc_match:
        on_line_value = wc_match.group(1).strip()
        if on_line_value in ('null', '~'):
            pass  # null — no existing entries
        else:
            # Either empty (list follows on next lines) or somehow inline.
            # Collect indented `- year:` items from the lines after the
            # `wiki_current_articles:` line.
            start = wc_match.end()
            rest = block[start:]
            for em in re.finditer(
                r'^    - year:\s*(\d{4})\s*\n      title:\s*"?([^"\n]+?)"?\s*$',
                rest, re.MULTILINE,
            ):
                existing_years.add(int(em.group(1)))
                existing_titles.append((int(em.group(1)), em.group(2).strip()))
    fields['_existing_years'] = existing_years
    fields['_existing_titles'] = existing_titles
    return fields


def canonical_pattern(fields: dict) -> str | None:
    """Pull the title body (between year and "election") from any existing
    historical title for this council."""
    candidates = []
    for key in ('wiki_2026', 'wiki_prior'):
        v = fields.get(key, '')
        if v and v != 'null' and v != '~':
            candidates.append(v.strip('"'))
    for _, t in fields['_existing_titles']:
        candidates.append(t)
    for t in candidates:
        m = TITLE_RE.match(t)
        if m:
            return m.group(2)
    return None


def candidate_years(fields: dict) -> list[int]:
    cycle = fields.get('cycle', '')
    founded = COUNCIL_FOUNDED.get(fields['lad_code'], 0)
    if cycle == 'thirds':
        years = THIRDS_YEARS
    elif cycle == 'halves':
        years = HALVES_YEARS
    elif cycle == 'all-out':
        prior_year = fields.get('wiki_prior_year', '')
        try:
            py = int(prior_year)
        except (TypeError, ValueError):
            return []
        if py - 4 < 2018:
            return []
        years = [py - 4]
    else:
        years = []
    return [y for y in years if y >= founded]


def build_title(pattern: str, year: int, council_name: str) -> str:
    override = TITLE_OVERRIDES.get((council_name, year))
    if override is not None:
        return override
    return f"{year} {pattern} election"


def rewrite_wiki_current(block: str, new_entries: list[tuple[int, str]],
                         existing_titles: list[tuple[int, str]]) -> str:
    """Replace the `wiki_current_articles:` line (and any following list)
    in `block` with a fresh list containing both existing + new entries,
    newest-first. Format matches the file's `  - year: X` / `    title: "…"`
    indentation."""
    all_entries = sorted(existing_titles + new_entries, key=lambda e: -e[0])
    new_block_lines = ['  wiki_current_articles:']
    for year, title in all_entries:
        new_block_lines.append(f'    - year: {year}')
        new_block_lines.append(f'      title: "{title}"')
    new_block_text = '\n'.join(new_block_lines)

    # Find the full extent of the existing wiki_current_articles block:
    # either a `wiki_current_articles: null` single line, or
    # `wiki_current_articles:\n` followed by 4-space-indented list items.
    pattern = re.compile(
        r'^  wiki_current_articles:.*(?:\n    [- ].*)*',
        re.MULTILINE,
    )
    return pattern.sub(new_block_text, block, count=1)


def main():
    text = COUNCILS.read_text()
    # Split into blocks delimited by flush-left `- lad_code:` markers.
    parts = re.split(r'(?m)^(?=- lad_code:)', text)
    header = parts[0]  # everything before the first council
    council_blocks = parts[1:]

    out: list[str] = [header]
    touched = 0
    added = 0
    skipped: list[str] = []
    for block in council_blocks:
        fields = parse_council_block(block)
        lad = fields.get('lad_code', '').strip()
        name = fields.get('name', '').strip()
        if not lad.startswith(GB_PREFIXES):
            out.append(block)
            skipped.append(f"  {lad} {name} (out of GB scope)")
            continue
        pattern = canonical_pattern(fields)
        if pattern is None:
            out.append(block)
            skipped.append(f"  {lad} {name} (no canonical title pattern)")
            continue
        existing_years = fields['_existing_years']
        cand = [y for y in candidate_years(fields)
                if y not in existing_years and y != 2026]
        if not cand:
            out.append(block)
            continue
        new_entries = [(y, build_title(pattern, y, name)) for y in cand]
        new_block = rewrite_wiki_current(block, new_entries, fields['_existing_titles'])
        out.append(new_block)
        touched += 1
        added += len(new_entries)

    COUNCILS.write_text(''.join(out))

    print(f'Touched {touched} councils; added {added} historical wiki_current_articles entries.')
    if skipped:
        print(f'\nSkipped {len(skipped)} councils:')
        for line in skipped[:20]:
            print(line)
        if len(skipped) > 20:
            print(f'  … and {len(skipped) - 20} more')


if __name__ == '__main__':
    main()
