"""Parse Lincolnshire County Council 2025 results from lincolnshire.gov.uk.

Lincolnshire's vendor-hosted moderngov instance only ever held the
nomination list, not the declared results — so we scrape the council's
own `/council-business/elections/2` page instead, which embeds the full
70-division result set as 70 sibling `<h3>` + `<table>` blocks.

Per division:
    <h3>Alford and Sutton</h3>
    <table><tbody>
        <tr>  <!-- elected: every <td> wrapped in <strong> -->
            <td><strong>BEECHAM</strong></td>
            <td><strong>Mike</strong></td>
            <td><strong>Reform UK</strong></td>
            <td><strong>1,527</strong></td>
        </tr>
        <tr> <td>BINNS</td> <td>Mark</td> <td>Liberal Democrats</td> <td>68</td> </tr>
        ...
    </tbody></table>

The page lists the winner first (and bolds every cell), so picking the
first `<tr>` of each table is equivalent to picking the elected row.
Surnames are uppercased; forename casing is mixed; the CSV emits
"Forename SURNAME" as a single candidate string.
"""
import html
import re
import urllib.parse

from _wiki_parser import normalize_party

extension = 'html'

SECTION_RE = re.compile(
    r'<h3>([^<]+)</h3>\s*(?:<[^>]+>\s*)*<table[^>]*>(.*?)</table>',
    re.DOTALL | re.IGNORECASE,
)

# First <tr> inside the table — the winner row. Cells may be wrapped in
# <strong>; <td> may carry a width="…" attribute. The bare-text capture
# groups handle either case (the </?strong> tags are stripped before the
# tighter inner pattern).
ROW_RE = re.compile(
    r'<tr[^>]*>\s*'
    r'<td[^>]*>\s*(?:<strong>)?\s*([^<]+?)\s*(?:</strong>)?\s*</td>\s*'
    r'<td[^>]*>\s*(?:<strong>)?\s*([^<]+?)\s*(?:</strong>)?\s*</td>\s*'
    r'<td[^>]*>\s*(?:<strong>)?\s*([^<]+?)\s*(?:</strong>)?\s*</td>\s*'
    r'<td[^>]*>\s*(?:<strong>)?\s*([\d,]+)\s*(?:</strong>)?\s*</td>',
    re.DOTALL | re.IGNORECASE,
)


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    page = content.decode('utf-8', errors='replace')
    is_county = council['lad_code'].startswith('E10')
    source = urllib.parse.urlparse(council['official_url']).netloc

    out: list[dict] = []
    for sec in SECTION_RE.finditer(page):
        division = html.unescape(sec.group(1)).strip()
        table = sec.group(2)
        row = ROW_RE.search(table)
        if not row:
            continue
        surname  = html.unescape(row.group(1)).strip()
        forename = html.unescape(row.group(2)).strip()
        party    = html.unescape(row.group(3)).strip()
        votes    = int(row.group(4).replace(',', ''))
        candidate = f'{forename} {surname}'.strip()
        rec = {
            'lad_code':  council['lad_code'],
            'party':     normalize_party(party),
            'candidate': candidate,
            'votes':     votes,
            'source':    source,
        }
        if is_county:
            rec['county']   = council['name']
            rec['division'] = division
        else:
            rec['council'] = council['name']
            rec['ward']    = division
        out.append(rec)
    return out
