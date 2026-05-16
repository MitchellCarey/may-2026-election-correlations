"""Parse Hull City Council 2026 ward results from the news.hull.gov.uk
live blog.

Hull's bespoke "results" page is a WordPress live blog. Each declared
ward appears as

    <h2|h3 class="wp-block-heading">WardName ward result</h2|h3>
    <p>Party <strong>GAIN/HOLD</strong> (Candidate Name)</p>

The blog post mixes h2 and h3 ward headings (about 8 + 12 at time of
writing). There are **no vote counts on the live blog**; per-ward
declaration PDFs are uploaded later and feed issue #53. The schema's
`votes` column is set to 0 here so the row is still complete.

Hull is a halves council, so each row is one elected councillor and
`pick_plurality` is a pass-through.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party

extension = 'html'

# Match h2 or h3 with class wp-block-heading whose text ends "ward result".
WARD_HEAD_RE = re.compile(
    r'<h[23][^>]*class="wp-block-heading"[^>]*>\s*'
    r'([^<]+?)\s+ward result\s*</h[23]>',
    re.IGNORECASE,
)

# `<p>Party <strong>GAIN|HOLD</strong> (Candidate Name)</p>`. The closing
# `</strong>` sometimes carries a stray trailing space inside it (e.g.
# `HOLD </strong>(Linda Chambers)` in the Drypool block), so allow space
# between `</strong>` and the opening `(`.
RESULT_LINE_RE = re.compile(
    r'<p[^>]*>\s*([^<]+?)\s*<strong[^>]*>\s*(?:GAIN|HOLD)\s*</strong>\s*\(\s*([^)]+?)\s*\)\s*</p>',
    re.IGNORECASE,
)


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    src = content.decode('utf-8', errors='replace')
    source = urllib.parse.urlparse(council['official_url']).netloc

    out: list[dict] = []
    ward_heads = list(WARD_HEAD_RE.finditer(src))
    for i, m in enumerate(ward_heads):
        ward_name = html.unescape(m.group(1).strip())
        block_start = m.end()
        block_end = ward_heads[i + 1].start() if i + 1 < len(ward_heads) else len(src)
        rm = RESULT_LINE_RE.search(src, block_start, block_end)
        if not rm:
            continue
        party_raw = html.unescape(rm.group(1).strip())
        candidate = html.unescape(rm.group(2).strip())
        out.append({
            'lad_code':  council['lad_code'],
            'council':   council['name'],
            'ward':      ward_name,
            'party':     normalize_party(party_raw),
            'candidate': candidate,
            'votes':     0,
            'source':    source,
        })
    return out
