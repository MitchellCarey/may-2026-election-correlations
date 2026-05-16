"""Shared helpers for PDF declaration-of-poll parsers.

Several Phase 4 councils publish per-ward results as one PDF per ward,
linked from a single index page. Each parser:

  fetch(): walks the council's index page, collects {ward_name: pdf_url},
           hands the pairs to bundle_pdfs() to retrieve and pack into one
           zip cache (one ZIP per council, one PDF member per ward).

  parse(): hands the zip bytes to iter_pdfs() to recover (ward_name,
           pdf_bytes) members, then runs council-specific table extraction
           (the elected-row sentinel differs per council: "Elected" in its
           own column for Hartlepool, " E" suffix on votes for Newham,
           " Elected" inline with votes for Redditch).

`pdfplumber` is lazy-imported inside the per-council parse() functions, not
here — this module is import-clean for contributors not running a PDF parser.
"""
import io
import time
import urllib.request
import zipfile
from collections.abc import Iterator


UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36 '
      'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)')


def http_get(url: str, *, ua: str = UA, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def bundle_pdfs(name_to_url: dict[str, str], *, ua: str = UA,
                delay: float = 0.3) -> bytes:
    """Fetch every PDF in name_to_url and return a ZIP archive whose
    members are named '<sanitised name>.pdf'. Order is preserved."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, (name, url) in enumerate(name_to_url.items()):
            if i:
                time.sleep(delay)  # be polite
            pdf = http_get(url, ua=ua)
            safe = name.replace('/', '_')
            zf.writestr(f'{safe}.pdf', pdf)
    return buf.getvalue()


def iter_pdfs(content: bytes) -> Iterator[tuple[str, bytes]]:
    """Yield (member_name_without_pdf_suffix, pdf_bytes) for each entry
    in the bundled cache. Order matches the ZIP central directory."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.lower().endswith('.pdf'):
                name = name[:-4]
            yield name, zf.read(info)
