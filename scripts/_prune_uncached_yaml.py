"""Post-fetch cleanup helper: remove wiki_current_articles entries from
councils.yaml whose cache file scripts/10 couldn't fetch (Wikipedia 404 —
council didn't contest that year, or had a different title format, or the
article simply doesn't exist on Wikipedia).

Without this, every `10` run re-tries the missing entries, wasting ~6
minutes on the 700-odd 404s the phase 1A expansion produced.

Not invoked by the pipeline. Leading underscore by convention. Companion
to scripts/_expand_history_yaml.py — run after `10` reports its misses.
Idempotent.

Run with: .venv/bin/python scripts/_prune_uncached_yaml.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COUNCILS = ROOT / 'data' / 'source' / 'councils.yaml'
CACHE = ROOT / 'data' / 'source'

ENTRY_RE = re.compile(
    # Use `[ \t]*` (not `\s*`) at line endings so we don't accidentally
    # eat the blank line between this council's block and the next.
    r'^    - year:[ \t]*(\d{4})[ \t]*\n      title:[ \t]*"?([^"\n]+?)"?[ \t]*$',
    re.MULTILINE,
)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def parse_council_block(block: str) -> dict:
    fields: dict = {}
    for m in re.finditer(r'^(?:- |  )([a-z_0-9]+):[ \t]*(.*)$', block, re.MULTILINE):
        fields[m.group(1)] = m.group(2).strip()
    return fields


def prune_block(block: str, name: str) -> tuple[str, int]:
    """Remove wiki_current_articles entries whose cache file doesn't exist.
    Returns (new_block, removed_count). Preserves everything outside the
    list — sibling fields, blank lines, trailing comments."""
    wc_match = re.search(
        r'^(  wiki_current_articles:)([ \t]*)(.*)$',
        block, re.MULTILINE
    )
    if not wc_match:
        return block, 0
    if wc_match.group(3).strip() in ('null', '~'):
        return block, 0  # nothing to prune

    # Find all entries in the block AFTER wc_match.
    after_start = wc_match.end()
    entries = list(ENTRY_RE.finditer(block, pos=after_start))
    if not entries:
        return block, 0

    # The list spans from just after the wc_match line to the end of the
    # last entry's match. Everything after that (sibling fields, blank
    # lines, trailing comments) is preserved verbatim.
    first_entry_start = entries[0].start()
    last_entry_end = entries[-1].end()

    kept: list[tuple[int, str]] = []
    removed = 0
    for em in entries:
        year = int(em.group(1))
        title = em.group(2).strip()
        cache_path = CACHE / f'wiki_current_{slug(name)}_{year}.json'
        if cache_path.exists():
            kept.append((year, title))
        else:
            removed += 1

    if removed == 0:
        return block, 0

    # The character between wc_match.end() and first_entry_start is a
    # newline; preserve it. The portion from last_entry_end onwards
    # (everything below the list) is preserved as-is.
    pre_list = block[wc_match.end():first_entry_start]  # newline after wc_match
    post_list = block[last_entry_end:]                  # trailing stuff

    if not kept:
        # No surviving entries — collapse back to `wiki_current_articles: null`.
        new_block = (
            block[:wc_match.start(2)]
            + ' null'
            + post_list
        )
    else:
        new_lines = [f'    - year: {y}\n      title: "{t}"' for y, t in kept]
        new_list_text = pre_list + '\n'.join(new_lines)
        new_block = (
            block[:wc_match.end()]
            + new_list_text
            + post_list
        )
    return new_block, removed


def main():
    text = COUNCILS.read_text()
    parts = re.split(r'(?m)^(?=- lad_code:)', text)
    header = parts[0]
    council_blocks = parts[1:]

    out: list[str] = [header]
    total_removed = 0
    councils_pruned = 0
    for block in council_blocks:
        fields = parse_council_block(block)
        name = fields.get('name', '').strip()
        new_block, removed = prune_block(block, name)
        if removed:
            councils_pruned += 1
            total_removed += removed
        out.append(new_block)

    COUNCILS.write_text(''.join(out))
    print(f'Pruned {total_removed} uncached wiki_current_articles entries '
          f'across {councils_pruned} councils.')


if __name__ == '__main__':
    main()
