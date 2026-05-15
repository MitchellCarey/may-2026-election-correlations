"""Parse Redditch Borough Council's per-ward declaration-of-poll PDFs.

Redditch publishes per-ward results from the elections page at
www.redditchbc.gov.uk/council/elections/current-elections-and-referendums/
redditch-borough-council-elections-7-may-2026/, with one PDF per ward at
/media/<hash>/<slug>-declaration-of-results.pdf.

Each PDF carries one elected councillor (Redditch elects in thirds, one
seat per ward per cycle). Table extraction returns a wide grid with a
candidate, a party and a votes column; the elected row's votes cell ends
in " Elected" (e.g. "652 Elected").
"""
import html
import io
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pdf_zip import bundle_pdfs, http_get, iter_pdfs

extension = 'zip'

# /media/<hash>/<slug>-declaration-of-results.pdf
WARD_PDF_RE = re.compile(
    r'href="(/media/[^"]+?-declaration-of-results\.pdf)"',
    re.IGNORECASE,
)

ELECTED_VOTES_RE = re.compile(r'^([\d,]+)\s+Elected$', re.IGNORECASE)

# The PDF body's "Election of a Borough Councillor for\n<WARD>\non Thursday…"
# carries the canonical ward name (URL slug drops "and"/ampersand joins).
WARD_NAME_RE = re.compile(
    r'Election of a Borough Councillor for\s*\n([^\n]+?)\s*\non\s+Thursday',
    re.IGNORECASE,
)


def _ward_name_from_text(pdf_text: str) -> str:
    m = WARD_NAME_RE.search(pdf_text)
    if not m:
        raise ValueError('Redditch PDF missing canonical ward name line')
    # Council uses "&"; normalise to "and" to match WD24 + Wikipedia.
    return re.sub(r'\s*&\s*', ' and ', m.group(1).strip())


def fetch(url: str, *, council: dict, year: int) -> bytes:
    index_html = http_get(url).decode('utf-8', errors='replace')
    parsed = urllib.parse.urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}'
    # Key zip members by URL-slug since the canonical ward name isn't
    # known until parse() opens the PDF.
    pairs: dict[str, str] = {}
    for m in WARD_PDF_RE.finditer(index_html):
        href = html.unescape(m.group(1))
        slug_m = re.search(r'/([a-z0-9-]+)-declaration-of-results\.pdf$', href, re.I)
        if not slug_m:
            continue
        slug = slug_m.group(1)
        if slug in pairs:
            continue
        pairs[slug] = base + href
    return bundle_pdfs(pairs)


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    for _slug, pdf_bytes in iter_pdfs(content):
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            ward_name = _ward_name_from_text(pdf.pages[0].extract_text() or '')
            for page in pdf.pages:
                done = False
                for table in page.extract_tables():
                    for row in table:
                        # Cells may be None for empty grid columns; collapse
                        # to the non-empty values and pick the elected row.
                        cells = [(c or '').strip() for c in row if c is not None]
                        cells = [c for c in cells if c]
                        if len(cells) < 3:
                            continue
                        votes_match = None
                        for c in cells:
                            votes_match = ELECTED_VOTES_RE.match(c)
                            if votes_match:
                                break
                        if not votes_match:
                            continue
                        # Order in the row is: candidate, party, "VOTES Elected".
                        idx = cells.index(votes_match.string)
                        if idx < 2:
                            continue
                        candidate = re.sub(
                            r'\s+commonly\s+known\s+as\s+.*$', '',
                            cells[idx - 2], flags=re.I | re.S,
                        ).replace('\n', ' ').strip()
                        party_raw = cells[idx - 1].replace('\n', ' ').strip()
                        votes = int(votes_match.group(1).replace(',', ''))
                        out.append({
                            'lad_code':  council['lad_code'],
                            'council':   council['name'],
                            'ward':      ward_name,
                            'party':     normalize_party(party_raw),
                            'candidate': candidate,
                            'votes':     votes,
                            'source':    'redditchbc.gov.uk',
                        })
                        done = True
                        break
                    if done:
                        break
                if done:
                    break
    return out
