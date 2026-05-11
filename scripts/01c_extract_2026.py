"""Parse cached 2026-election Wikipedia wikitext into per-ward winners.

Mirror of 01b for the current election. Reads data/source/wiki_<slug>_2026.json
(produced by 00b) for every council in data/source/councils.yaml with a
wiki_2026 set, and writes:

    data/results_2026_scraped.json
        { council_name: { ward_name: { "party": <str> } } }

GM councils are absent from this output by design (their wiki_2026 is null
because the hand-curated CSV at data/source/results_2026.csv is the source
of truth for GM). 01 merges the two in a later step.

Top-of-poll selection and party normalisation are identical to 01b — the
same `{{Election box winning candidate}}` template applies on both pages.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from _councils import for_region
from _wiki_parser import parse_article

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"

UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'
WIKI_API = 'https://en.wikipedia.org/w/api.php'


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _fetch_per_ward_article(page_title: str) -> str | None:
    """Return the wikitext of a Wikipedia per-ward article, caching to
    data/source/wiki_xclude_<slug>.json on first fetch. Returns None on a
    Wikipedia 404 / parse error (e.g. the per-ward page doesn't exist)."""
    cache_path = SOURCE / f'wiki_xclude_{slug(page_title)}.json'
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f).get('parse', {}).get('wikitext')
    qs = urllib.parse.urlencode({
        'action': 'parse', 'page': page_title, 'format': 'json',
        'formatversion': '2', 'prop': 'wikitext', 'redirects': '1',
    })
    req = urllib.request.Request(f'{WIKI_API}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    if 'error' in data:
        # Cache the miss so we don't keep retrying every run.
        with open(cache_path, 'w') as f:
            json.dump(data, f)
        return None
    with open(cache_path, 'w') as f:
        json.dump(data, f)
    time.sleep(0.5)
    return data.get('parse', {}).get('wikitext')


def fetch_transclusion(page_title: str, section_label: str) -> str | None:
    """Resolve a {{#section:Page|Label}} call by fetching the page and
    extracting the substring between matching <section begin="Label" /> and
    <section end="Label" /> markers. Returns None if either the page or the
    label is missing."""
    wt = _fetch_per_ward_article(page_title)
    if wt is None:
        return None
    pattern = re.compile(
        r'<section\s+begin\s*=\s*"?' + re.escape(section_label) + r'"?\s*/?>'
        r'(.*?)'
        r'<section\s+end\s*=\s*"?' + re.escape(section_label) + r'"?\s*/?>',
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(wt)
    return m.group(1) if m else None


def main():
    out = {}
    summary_rows = []
    missing_cache = []
    for council in for_region("gb"):
        if not council.get("wiki_2026"):
            continue
        # English county council (E10*) articles are organised "candidates by
        # local authority" — H3 sections are DISTRICT names, not electoral
        # divisions. The parser can't recover real division-level results from
        # them, so the would-be pseudo-wards (district names) only pollute
        # downstream matching as NOT FOUND. Skip until a CED-aware parser +
        # CED-to-CTY lookup are added (tracked as a follow-up to issue #3).
        if council["lad_code"].startswith("E10"):
            continue
        name = council["name"]
        path = SOURCE / f'wiki_{slug(name)}_2026.json'
        if not path.exists():
            missing_cache.append((council["lad_code"], name))
            continue
        with open(path) as f:
            wt = json.load(f)['parse']['wikitext']
        winners = parse_article(name, 2026, wt, fetch_transclusion=fetch_transclusion)
        # parse_article returns {ward: {prior_party, prior_year}}; reshape to
        # {ward: {party}} for the 2026 output.
        out[name] = {w: {'party': rec['prior_party']} for w, rec in winners.items()}
        counts: dict[str, int] = {}
        for rec in out[name].values():
            counts[rec['party']] = counts.get(rec['party'], 0) + 1
        summary_rows.append((name, len(out[name]), counts))

    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / 'results_2026_scraped.json', 'w') as f:
        json.dump(out, f, indent=2)

    total = sum(len(v) for v in out.values())
    print(f'Saved results_2026_scraped.json — {total} wards across {len(out)} councils')
    if missing_cache:
        print(f'  ({len(missing_cache)} councils have wiki_2026 but no cached file; run scripts/00b_fetch_2026_results.py)')
    print()
    for name, n, counts in summary_rows:
        print(f'  {name:>30}: {n:>3} wards | {counts}')


if __name__ == '__main__':
    main()
