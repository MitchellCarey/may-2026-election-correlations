"""Parse Sunderland City Council's per-ward declaration-of-poll PDFs.

www.sunderland.gov.uk is fronted by Cloudflare and 403s vanilla urllib
clients, so both the index page and every per-ward PDF are fetched via
_cloudflare.cloudflare_session() (curl_cffi chrome120 TLS impersonation).

The article at /article/39917/Result-of-Poll-By-Ward-7-May-2026 is an
index that links to 25 per-ward "Multi Declaration" PDFs (each served
with Content-Type: application/pdf despite the .html-shaped URL). One
PDF per ward, one page per PDF, listing every candidate and their votes.

Sunderland ran all-up in 2026 following a 2024 boundary review, so most
wards elect three councillors. The PDFs carry no explicit "Elected"
marker, so we read the seat count from the header line
    "Election of {one|two|three} Councillors to Sunderland City Council
     for {Ward Name} Ward"
sort the candidates by votes descending, take the top N as elected, then
hand the elected rows to _pick_winner.pick_plurality.

Each candidate appears as a pair of consecutive text lines:
    "Forename(s) SURNAME N,NNN"
    "Party name"
The candidate-row regex requires a fully-uppercase 2+ char token (the
surname) immediately before the votes; this rejects footer lines like
"Want of Official Mark 0" and "Total Rejected 14" which have no
sustained run of uppercase letters.
"""
import html as _html
import io
import re
import urllib.parse
import zipfile

from _wiki_parser import normalize_party
from _official_parsers._cloudflare import cloudflare_session
from _official_parsers._pdf_zip import iter_pdfs
from _official_parsers._pick_winner import pick_plurality

extension = 'zip'

INDEX_LINK_RE = re.compile(
    r'<a class="item__link" href="([^"]+)">\s*'
    r'Result of Poll - Local Government Election May 2026 -\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)

SEAT_COUNT_RE = re.compile(
    r'Election of (\w+) Councillors? to Sunderland City Council',
    re.IGNORECASE,
)

NUMBER_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}

CANDIDATE_LINE_RE = re.compile(r"^(.*[A-Z]{2,}[A-Z'\-]*)\s+([\d,]+)\s*$")


def fetch(url: str, *, council: dict, year: int) -> bytes:
    """Walk the Cloudflare-protected index, fetch every per-ward PDF,
    return a ZIP keyed by ward name. One session keeps cf_clearance hot
    across all 26 GETs (1 index + 25 PDFs)."""
    parsed = urllib.parse.urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}'

    buf = io.BytesIO()
    with cloudflare_session() as s:
        idx_resp = s.get(url)
        if idx_resp.status_code != 200:
            raise RuntimeError(
                f'Cloudflare bypass returned HTTP {idx_resp.status_code} for {url}'
            )
        idx_html = idx_resp.content.decode('utf-8', errors='replace')

        seen: set[str] = set()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for m in INDEX_LINK_RE.finditer(idx_html):
                href = _html.unescape(m.group(1)).strip()
                name = _html.unescape(m.group(2)).strip()
                if name in seen:
                    continue
                seen.add(name)
                full = href if href.startswith('http') else base + href
                pdf_resp = s.get(full)
                if pdf_resp.status_code != 200:
                    raise RuntimeError(
                        f'Cloudflare bypass returned HTTP {pdf_resp.status_code} for {full}'
                    )
                safe = name.replace('/', '_')
                zf.writestr(f'{safe}.pdf', pdf_resp.content)
    return buf.getvalue()


def parse(content: bytes, *, council: dict, year: int) -> list[dict]:
    import pdfplumber

    source = urllib.parse.urlparse(council['official_url']).netloc

    out: list[dict] = []
    for ward_name, pdf_bytes in iter_pdfs(content):
        # The council's index uses '&' between merged ward halves
        # (e.g. "Barnes & Thornhill"), but all_wards.json and the
        # boundary-review rows in ward_name_overrides.csv use " and ";
        # 04c's geom_overrides lookup compares verbatim strings, so
        # emit the "and" spelling for the join to land.
        ward_name = ward_name.replace(' & ', ' and ')
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = '\n'.join((p.extract_text() or '') for p in pdf.pages)

        seat_m = SEAT_COUNT_RE.search(text)
        seats = NUMBER_WORDS.get(seat_m.group(1).lower()) if seat_m else None
        if not seats:
            continue

        lines = [ln.strip() for ln in text.split('\n')]
        start = 0
        for i, ln in enumerate(lines):
            if ln.lower().startswith('name of candidate'):
                start = i + 1
                break

        rows: list[tuple[str, str, int]] = []
        i = start
        while i < len(lines):
            cm = CANDIDATE_LINE_RE.match(lines[i])
            if cm:
                candidate = cm.group(1).strip()
                votes = int(cm.group(2).replace(',', ''))
                party_raw = ''
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if not nxt:
                        j += 1
                        continue
                    if CANDIDATE_LINE_RE.match(nxt):
                        break
                    if nxt.lower().startswith('rejected ballot papers'):
                        break
                    party_raw = nxt
                    break
                if party_raw:
                    rows.append((party_raw, candidate, votes))
                    i = j + 1
                    continue
            i += 1

        rows.sort(key=lambda r: r[2], reverse=True)
        winner = pick_plurality(rows[:seats])
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
            'source':    source,
        })
    return out
