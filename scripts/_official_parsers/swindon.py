"""Parse Swindon Borough Council 2026 ward results from swindon.gov.uk.

Single HTML page lists all 25 post-boundary-review wards inline. Each
ward block opens with `<caption>Candidates and votes &ndash; {Ward}
</caption>` inside its own `<table>`, followed by a `<tbody>` of
`<tr><td>NAME</td><td>PARTY</td><td>VOTES Elected</td></tr>` rows. The
literal " Elected" suffix on the votes cell marks the winning row(s);
losing rows have just the digits.

Swindon ran all-up in 2026 due to a 2024 boundary review, so most wards
return two or three elected councillors. Following the existing parser
convention (see salford.py, moderngov_per_division.py) we yield only the
first-listed elected candidate per ward, which is enough to paint the map.

`official_url` is the canonical results page; default urllib GET works
(no Cloudflare). The cached file is the raw HTML.
"""
import html
import re
import sys
import urllib.parse

from _wiki_parser import normalize_party

extension = 'html'

# Each ward's results table is the only place this caption text appears,
# and the ward name follows the &ndash; entity verbatim. The page header
# h2 "Borough election results 2026" has no caption, so this pattern
# discriminates ward tables from the summary table at the top of the page.
CAPTION_RE = re.compile(
    r'<caption>\s*Candidates and votes\s*&ndash;\s*([^<]+?)\s*</caption>',
    re.IGNORECASE,
)

# Three <td>s in order: candidate, party, "VOTES Elected". The trailing
# "Elected" sentinel is what distinguishes winning rows from losing ones.
# The separator between votes and "Elected" is usually a literal space but
# in Priory Vale's block it's an `&nbsp;` entity — accept either.
ELECTED_ROW_RE = re.compile(
    r'<tr[^>]*>\s*'
    r'<td[^>]*>\s*([^<]+?)\s*</td>\s*'
    r'<td[^>]*>\s*([^<]+?)\s*</td>\s*'
    r'<td[^>]*>\s*([\d,]+)(?:\s|&nbsp;)+Elected\s*</td>\s*'
    r'</tr>',
    re.DOTALL | re.IGNORECASE,
)


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    src = content.decode('utf-8', errors='replace')
    source = urllib.parse.urlparse(council['official_url']).netloc

    captions = list(CAPTION_RE.finditer(src))
    out: list[dict] = []
    missing: list[str] = []
    for i, m in enumerate(captions):
        ward_name = html.unescape(m.group(1).strip())
        block_start = m.end()
        block_end = captions[i + 1].start() if i + 1 < len(captions) else len(src)
        em = ELECTED_ROW_RE.search(src, block_start, block_end)
        if not em:
            missing.append(ward_name)
            continue
        out.append({
            'lad_code':  council['lad_code'],
            'council':   council['name'],
            'ward':      ward_name,
            'party':     normalize_party(html.unescape(em.group(2).strip())),
            'candidate': html.unescape(em.group(1).strip()),
            'votes':     int(em.group(3).replace(',', '')),
            'source':    source,
        })

    if missing:
        print(
            f'  ! Swindon: {len(missing)} ward(s) had no "Elected" row: '
            f'{", ".join(missing)}',
            file=sys.stderr,
        )
    return out
