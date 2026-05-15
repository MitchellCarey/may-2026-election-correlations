"""Parse Newham London Borough Council's per-ward declaration-of-poll PDFs.

Newham publishes per-ward results from a paginated CMS document at
www.newham.gov.uk/council/local-elections-2026-results, where each
chapter is a sub-URL ?/N (page 1 = intro, 2 = mayoral, 3..N = wards).
Each ward subpage links one PDF at /downloads/file/<id>/<slug>-result-sheet.

PDFs carry multiple elected councillors (Newham elects all 24 wards
simultaneously, three-member or two-member). The first table on the page
has 3 columns: candidate, party, votes-with-optional-" E"-suffix. Elected
rows have votes ending " E"; we feed every elected row to
_pick_winner.pick_plurality.
"""
import html
import io
import re
import time
import urllib.parse
import urllib.error

from _wiki_parser import normalize_party
from _official_parsers._pdf_zip import bundle_pdfs, http_get, iter_pdfs
from _official_parsers._pick_winner import pick_plurality

extension = 'zip'

# The full PDF URL is hard-coded with the council's own host.
PDF_LINK_RE = re.compile(
    r'href="(https?://[^"]*/downloads/file/\d+/[^"]+?-result-sheet)"',
    re.IGNORECASE,
)

# Page title pattern: "<Ward Name> – Local Elections 2026 Results – Newham Council"
TITLE_RE = re.compile(
    r'<title>([^<]+?)\s*–\s*Local Elections 2026 Results',
    re.IGNORECASE,
)

# Elected rows have votes ending in " E" — e.g. "1033 E".
ELECTED_VOTES_RE = re.compile(r'^([\d,]+)\s+E$', re.IGNORECASE)


def _walk_subpages(url: str) -> dict[str, str]:
    """Walk the paginated CMS document, return {ward_name: pdf_url}.

    Stops at the first 404, or at MAX_PAGES if the CMS ever serves a
    soft-200 for missing chapters instead of raising. Skips pages whose
    title is "Newham Council Elections 2026" (intro) or "Mayoral
    Election Result".
    """
    MAX_PAGES = 50  # Newham has 24 wards + intro + mayoral = 26 chapters
    parsed = urllib.parse.urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}'
    pairs: dict[str, str] = {}
    n = 1
    while n <= MAX_PAGES:
        try:
            page = http_get(f'{url.rstrip("/")}/{n}' if n > 1 else url
                            ).decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise
        title_m = TITLE_RE.search(page)
        title = title_m.group(1).strip() if title_m else ''
        if title and 'Mayoral' not in title and 'Elections 2026' not in title:
            link_m = PDF_LINK_RE.search(page)
            if link_m:
                pairs[title] = html.unescape(link_m.group(1))
                if not pairs[title].startswith('http'):
                    pairs[title] = base + pairs[title]
        n += 1
        time.sleep(0.2)
    return pairs


def fetch(url: str, *, council: dict, year: int) -> bytes:
    pairs = _walk_subpages(url)
    return bundle_pdfs(pairs)


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    for ward_name, pdf_bytes in iter_pdfs(content):
        elected: list[tuple[str, str, int]] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    for row in table:
                        cells = [(c or '').strip() for c in row if c is not None]
                        cells = [c for c in cells if c]
                        if len(cells) < 3:
                            continue
                        m = ELECTED_VOTES_RE.match(cells[-1])
                        if not m:
                            continue
                        candidate = cells[0].replace('\n', ' ').strip()
                        party_raw = cells[1].replace('\n', ' ').strip()
                        votes = int(m.group(1).replace(',', ''))
                        elected.append((party_raw, candidate, votes))
        winner = pick_plurality(elected)
        if winner is None:
            continue
        party_raw, candidate, votes = winner
        out.append({
            'lad_code':  council['lad_code'],
            'council':   council['name'],
            'ward':      ward_name,
            'party':     normalize_party(party_raw),
            'candidate': candidate,
            'votes':     votes,
            'source':    'newham.gov.uk',
        })
    return out
