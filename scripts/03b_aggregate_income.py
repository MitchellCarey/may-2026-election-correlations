"""Aggregate ONS small-area income estimates from MSOA to ward level.

One-off, idempotent. Skips work if data/ward_income.json already exists
unless --force is passed. Mirrors the pattern in scripts/09_fetch_ward_boundaries.py.

Pipeline:
  1. Read data/source/Income Estimates Small Areas.xlsx, sheet "Net income
     before housing costs" — the standard ONS small-area income headline,
     mean equivalised household income (£/yr) after tax/NI/benefits and
     before housing costs. ~7,200 rows, one per 2021 MSOA in England & Wales.
  2. Fetch (cached, idempotent) two ONS Open Geography Portal lookups:
       - OA_LSOA_MSOA_EW_DEC_2021_LU_v3 — OA21CD → MSOA21CD (exact fit;
         OAs nest perfectly into MSOAs).
       - OA21_WD24_LAD24_EW_LU_v2 — OA21CD → (WD24CD, WD24NM, LAD24CD)
         (best fit; wards do not perfectly contain OAs).
     Both layers paginate at 2000 rows; England & Wales has ~188k OAs so
     each lookup takes ~95 pages. Cached as CSV in data/source/ on first
     fetch; subsequent runs reuse the cache. The caches are gitignored.
  3. For each ward, compute a weighted-mean MSOA income:
         ward_income[w] = sum(MSOA_income[msoa_of(oa)]) / count(OAs in w)
     where the weight is the count of OAs in the ward that fall in each
     MSOA. Because OAs are designed by ONS to be roughly equal in
     population (target ~310 residents; actual 50–625), OA-count is a
     close proxy for population-weighting at this aggregation scale.
     Wards that genuinely span multiple MSOAs (common in urban GM) get
     a proper weighted blend; wards fully contained in one MSOA simply
     inherit that MSOA's value.
  4. Write data/ward_income.json. Key: "{LAD24CD}::{normalised ward name}"
     (NOT WD24CD) — the project's Census data uses a mix of ward code
     vintages (TS006 has wards as of Census 2021 publication, but Bolton
     was re-coded in May 2024, etc.) so keying by code would lose ~half
     of GM. Keying by (LAD, normalised name) is stable across boundary-
     review code churn: Bolton's "Astley Bridge" is still "Astley Bridge"
     in 2021 and 2024 codes alike. The normalisation mirrors
     scripts/02_match_gss.py's _normalize().

Build-only — output (data/ward_income.json) is consumed by 04_consolidate.py
as if it were another Census variable, then surfaces through the rest of
the Winners/Changes/Map pipelines like the existing TS022 fields.
"""
import argparse
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOURCE = DATA / "source"
OUT = DATA / "ward_income.json"

INCOME_XLSX = SOURCE / "Income Estimates Small Areas.xlsx"
INCOME_SHEET = "Net income before housing costs"
INCOME_HEADER_ROW = 4  # row 4 in the workbook = index 3
INCOME_MSOA_COL = 0    # column A
INCOME_MEAN_COL = 6    # column G ("Disposable (net) annual income before housing costs (£)")

OA_MSOA_CACHE = SOURCE / "oa21_msoa21_lookup.csv"
OA_WARD_CACHE = SOURCE / "oa21_wd24_lookup.csv"

OA_MSOA_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'OA_LSOA_MSOA_EW_DEC_2021_LU_v3/FeatureServer/0/query'
)
OA_WARD_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'OA21_WD24_LAD24_EW_LU_v2/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'


def http_get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f'{url}?{qs}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_paginated(endpoint: str, out_fields: list[str], label: str) -> list[dict]:
    """Paginate an ArcGIS FeatureServer/0/query — same pattern as script 09's
    fetch_lookup, generalised. ONS lookups cap at 2000 rows per request."""
    page_size = 2000
    offset = 0
    rows = []
    while True:
        params = {
            'where':             '1=1',
            'outFields':         ','.join(out_fields),
            'returnGeometry':    'false',
            'f':                 'json',
            'resultRecordCount': page_size,
            'resultOffset':      offset,
            'orderByFields':     out_fields[0],
        }
        d = http_get(endpoint, params)
        if d.get('error'):
            raise RuntimeError(f'{label} query failed: {d["error"]}')
        feats = d.get('features', [])
        for f in feats:
            rows.append(f['attributes'])
        print(f'  {label} offset={offset} → {len(feats)} rows (running total {len(rows)})')
        if not d.get('exceededTransferLimit'):
            break
        offset += len(feats)
        time.sleep(0.2)
    return rows


def load_or_fetch_lookup(cache: Path, endpoint: str, fields: list[str], label: str) -> list[dict]:
    """Return [{<field>: <value>, ...}, ...], fetching and caching as CSV if needed."""
    if cache.exists():
        print(f'  {label}: reusing cached {cache.relative_to(ROOT)}')
        with open(cache, newline='') as f:
            return list(csv.DictReader(f))
    print(f'  {label}: fetching from ONS Open Geography Portal...')
    rows = fetch_paginated(endpoint, fields, label)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in fields})
    print(f'  {label}: cached → {cache.relative_to(ROOT)}')
    return [{k: r.get(k) for k in fields} for r in rows]


def normalize_ward(s: str) -> str:
    """Loose-match key for joining the project's ward names against ONS
    WD24 ward names. More aggressive than scripts/02_match_gss.py::_normalize
    because the income lookup spans a wider range of orthographic noise
    (e.g. Tameside's "Dukinfield/Stalybridge" vs ONS "Dukinfield Stalybridge",
    or Trafford's "Gorse Hill and Cornbrook" vs ONS "Gorse Hill & Cornbrook"):
    expand '&' → 'and' first, strip a trailing parenthesised disambiguator,
    then collapse anything that isn't a letter/digit to a single space."""
    s = s.lower().replace('&', ' and ')
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s)
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return ' '.join(s.split())


def ward_key(lad_code: str, ward_name: str) -> str:
    return f'{lad_code}::{normalize_ward(ward_name)}'


def read_msoa_income() -> dict[str, float]:
    """Return {MSOA21CD: mean_income_£yr}. Income column is row 4 header,
    column G — value is a £ integer (or sometimes string with commas)."""
    if not INCOME_XLSX.exists():
        raise FileNotFoundError(
            f'{INCOME_XLSX.relative_to(ROOT)} not found — download from ONS:\n'
            f'https://www.ons.gov.uk/peoplepopulationandcommunity/'
            f'personalandhouseholdfinances/incomeandwealth/datasets/'
            f'smallareaincomeestimatesformiddlelayersuperoutputareasenglandandwales'
        )
    wb = openpyxl.load_workbook(INCOME_XLSX, data_only=True, read_only=True)
    if INCOME_SHEET not in wb.sheetnames:
        raise RuntimeError(
            f'sheet {INCOME_SHEET!r} not found in {INCOME_XLSX.name}; '
            f'sheets present: {wb.sheetnames}'
        )
    ws = wb[INCOME_SHEET]
    out = {}
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i <= INCOME_HEADER_ROW:
            continue
        msoa = row[INCOME_MSOA_COL]
        val = row[INCOME_MEAN_COL]
        if not msoa or not isinstance(msoa, str) or not msoa.startswith('E02'):
            continue
        if val is None:
            continue
        # The Excel column is numeric, but defensively coerce strings with commas.
        if isinstance(val, str):
            val = float(val.replace(',', '').strip())
        out[msoa] = float(val)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--force', action='store_true', help='Re-run even if data/ward_income.json exists')
    args = ap.parse_args()

    if OUT.exists() and not args.force:
        print(f'{OUT.relative_to(ROOT)} exists — skipping. Use --force to rebuild.')
        return

    SOURCE.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    print(f'1. Reading {INCOME_XLSX.name} → MSOA mean income...')
    msoa_income = read_msoa_income()
    print(f'   {len(msoa_income)} MSOA rows with income data')

    print('2a. OA21 → MSOA21 lookup...')
    oa_msoa_rows = load_or_fetch_lookup(
        OA_MSOA_CACHE, OA_MSOA_ENDPOINT, ['OA21CD', 'MSOA21CD'], 'OA21→MSOA21'
    )
    oa_msoa = {r['OA21CD']: r['MSOA21CD'] for r in oa_msoa_rows}
    print(f'   {len(oa_msoa)} OA → MSOA rows')

    print('2b. OA21 → (WD24, ward name, LAD24) lookup...')
    oa_ward_rows = load_or_fetch_lookup(
        OA_WARD_CACHE, OA_WARD_ENDPOINT,
        ['OA21CD', 'WD24CD', 'WD24NM', 'LAD24CD'], 'OA21→WD24',
    )
    print(f'   {len(oa_ward_rows)} OA → Ward rows')

    print('3. Aggregating MSOA income → ward (OA-count weighted, keyed by LAD::name)...')
    # Group OAs by ward (LAD24CD, WD24NM); for each OA look up its MSOA's
    # income; average across the ward's OAs. OA-count is a close proxy for
    # population weighting because OAs target ~310 residents each (range
    # 50–625), so within a typical ward (50–200 OAs) the size variation
    # mostly averages out. Missing MSOAs (none expected in E&W) drop out
    # without skewing the average.
    ward_totals: dict[str, list[float]] = {}
    skipped_msoa = 0
    for row in oa_ward_rows:
        oa = row['OA21CD']
        msoa = oa_msoa.get(oa)
        if msoa is None:
            continue
        inc = msoa_income.get(msoa)
        if inc is None:
            skipped_msoa += 1
            continue
        key = ward_key(row['LAD24CD'], row['WD24NM'])
        ward_totals.setdefault(key, []).append(inc)

    out: dict[str, int] = {
        key: int(round(sum(vals) / len(vals)))
        for key, vals in ward_totals.items()
        if vals
    }

    OUT.write_text(json.dumps(out, separators=(',', ':')))
    print(f'\nDone. wrote {len(out)} wards → {OUT.relative_to(ROOT)}')
    if skipped_msoa:
        print(f'  (skipped {skipped_msoa} OA assignments whose MSOA had no income figure)')

    # Coverage sanity. GM = LAD codes E08000001..E08000010.
    if (DATA / 'all_wards.json').exists():
        with open(DATA / 'all_wards.json') as f:
            wards = json.load(f)
        gm_wards = [w for w in wards if (w.get('lad_code') or '').startswith('E08000')
                    and w['lad_code'] <= 'E08000010']
        gm_covered = sum(
            1 for w in gm_wards
            if ward_key(w['lad_code'], w['ward']) in out
        )
        print(f'  GM coverage: {gm_covered}/{len(gm_wards)} wards with income')
        if gm_covered < len(gm_wards):
            for w in gm_wards:
                if ward_key(w['lad_code'], w['ward']) not in out:
                    print(f'    miss: {w["borough"]} :: {w["ward"]} ({w.get("gss")})')


if __name__ == '__main__':
    main()
