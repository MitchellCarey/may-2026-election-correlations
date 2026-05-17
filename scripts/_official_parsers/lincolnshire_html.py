"""Parse Lincolnshire County Council 2025 results from lincolnshire.gov.uk.

Lincolnshire's vendor-hosted moderngov instance only ever held the
nomination list, not the declared results — so we scrape the council's
own `/council-business/elections/2` page instead, which embeds the full
70-division result set as 70 sibling `<h3>` + `<table>` blocks.

Per division, candidates are listed **alphabetically by surname**, and
the elected row's four `<td>` cells are each wrapped in `<strong>`:

    <h3>Boston North</h3>
    <table><tbody>
        <tr> <td>BROADHURST</td>           <td>Michael</td> <td>Green</td>       <td>116</td> </tr>
        <tr> <td>BROOMFIELD-DOUGLAS</td>   <td>Carol</td>   <td>Blue Rev.</td>   <td>40</td>  </tr>
        <tr> <td>CLARK</td>                 <td>Carole</td>  <td>Labour</td>      <td>143</td> </tr>
        <tr>  <!-- elected -->
            <td><strong>CULLEN</strong></td>
            <td><strong>Maggie</strong></td>
            <td><strong>Reform UK</strong></td>
            <td><strong>806</strong></td>
        </tr>
        <tr> <td>DANI</td>                  <td>Anton</td>   <td>Conservative</td><td>327</td> </tr>
        ...
    </tbody></table>

`parse()` keys off the `<strong>` wrapping to identify the winner —
*not* row position, since the alphabetically-first candidate is rarely
the winner. Surnames are uppercased; forename casing is mixed; the CSV
emits "Forename SURNAME" as a single candidate string.
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

# A candidate <tr> — surname / forename / party / votes. Cells of the
# elected row are each wrapped in <strong>; losing rows are bare. The
# `(?:<strong>)?` optional groups capture the inner text either way.
# `<td>` may also carry a width="…" attribute.
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
        rows = list(ROW_RE.finditer(table))
        if not rows:
            continue
        # Prefer the <strong>-wrapped row (the elected candidate); fall
        # back to highest-votes only if no row is bolded.
        strong_rows = [r for r in rows if '<strong>' in table[r.start():r.end()]]
        row = strong_rows[0] if strong_rows else max(
            rows, key=lambda r: int(r.group(4).replace(',', ''))
        )
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
