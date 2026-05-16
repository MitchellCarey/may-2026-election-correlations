"""Parse Hartlepool Borough Council's per-ward declaration-of-poll PDFs.

Hartlepool publishes one PDF per ward off a single index page at
www.hartlepool.gov.uk/downloads/download/634/local-government-elections-
declaration-of-results-7-may-2026 — actually a chrome HTML page that
links to 12 per-ward PDFs at /downloads/file/<id>/local-election-
results-<slug>-ward.

`official_url` in the registry is the index page. The custom fetch()
walks the index, gathers every ward link, downloads each PDF, and caches
the result as a single ZIP keyed by ward name.

Each PDF carries one elected councillor (Hartlepool elects in thirds, one
seat per ward per cycle). The first table on the page has 4 columns:
candidate, party, votes, "Elected"-or-blank. We pick the row whose 4th
cell is exactly "Elected".
"""
import html
import io
import re
import urllib.parse

from _wiki_parser import normalize_party
from _official_parsers._pdf_zip import bundle_pdfs, http_get, iter_pdfs

extension = 'zip'

WARD_LINK_RE = re.compile(
    r'href="(/downloads/file/\d+/local-election-results-[a-z0-9-]+-ward)"',
    re.IGNORECASE,
)


def _ward_name_from_slug(href: str) -> str:
    m = re.search(r'/local-election-results-([a-z0-9-]+)-ward$', href, re.I)
    if not m:
        raise ValueError(f'unrecognised Hartlepool ward href: {href}')
    # Slugs lower-case the council's '&' to '-and-'; .title() would then
    # capitalise to ' And '. WD24 uses '&' (e.g. 'Fens & Greatham',
    # 'Headland & Harbour'), so undo the slug substitution to match.
    return m.group(1).replace('-', ' ').title().replace(' And ', ' & ')


def fetch(url: str, *, council: dict, year: int) -> bytes:
    index_html = http_get(url).decode('utf-8', errors='replace')
    parsed = urllib.parse.urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}'
    pairs: dict[str, str] = {}
    for m in WARD_LINK_RE.finditer(index_html):
        href = html.unescape(m.group(1))
        name = _ward_name_from_slug(href)
        if name in pairs:
            continue
        pairs[name] = base + href
    return bundle_pdfs(pairs)


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    for ward_name, pdf_bytes in iter_pdfs(content):
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            done = False
            for page in pdf.pages:
                for table in page.extract_tables():
                    for row in table:
                        if not row or len(row) < 4:
                            continue
                        if (row[3] or '').strip().lower() != 'elected':
                            continue
                        candidate = re.sub(
                            r'\s*\(commonly known as:.*?\)\s*$', '',
                            re.sub(r'\s+', ' ', (row[0] or '').strip()),
                        ).strip()
                        party_raw = re.sub(r'\s+', ' ', (row[1] or '').strip())
                        votes_raw = (row[2] or '').strip().replace(',', '')
                        if not candidate or not votes_raw.isdigit():
                            continue
                        out.append({
                            'lad_code':  council['lad_code'],
                            'council':   council['name'],
                            'ward':      ward_name,
                            'party':     normalize_party(party_raw),
                            'candidate': candidate,
                            'votes':     int(votes_raw),
                            'source':    'hartlepool.gov.uk',
                        })
                        done = True
                        break
                    if done:
                        break
                if done:
                    break
    return out
