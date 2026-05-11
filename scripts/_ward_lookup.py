"""Cached ONS ward-to-LAD lookup.

The Census 2021 ward-level XLSX files use the May 2022 ward boundary vintage
(same codes as Dec 2021 for unchanged wards; Astley Bridge is E05000650 in
both the XLSX and the WD22 lookup). The newer WD24 lookup has different
codes for wards re-warded in 2023, so it doesn't join cleanly to the XLSX —
we use WD22 here for that reason.

Cache file: data/source/wd22_lad22_lookup.json. LAD22CD is identical to
LAD24CD for the councils we care about (the boundary changes since 2022
affected wards, not LADs).
"""
import functools
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "source" / "wd22_lad22_lookup.json"

LU_ENDPOINT = (
    'https://services1.arcgis.com/ESMARspQHYMw9BZ9/ArcGIS/rest/services/'
    'WD22_LAD22_UK_LU/FeatureServer/0/query'
)
UA = 'gm-2026-ward-analysis/1.0 (mitchellcarey2@gmail.com)'


def _fetch_all() -> dict[str, str]:
    """Page through the ONS lookup and return {WD22CD: LAD22CD} for all of UK."""
    out: dict[str, str] = {}
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "WD22CD,LAD22CD",
            "f": "json",
            "returnGeometry": "false",
            "returnDistinctValues": "true",
            "resultRecordCount": "2000",
            "resultOffset": str(offset),
        }
        url = f"{LU_ENDPOINT}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        feats = data.get("features", [])
        if not feats:
            break
        for f in feats:
            a = f["attributes"]
            out[a["WD22CD"]] = a["LAD22CD"]
        if not data.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return out


@functools.lru_cache(maxsize=1)
def load() -> dict[str, str]:
    """Return the cached {WD22CD: LAD22CD} lookup, fetching once if needed."""
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        lookup = _fetch_all()
        with open(CACHE, "w") as f:
            json.dump(lookup, f)
        print(f'Cached WD22->LAD22 lookup ({len(lookup)} wards) at {CACHE.relative_to(ROOT)}')
    with open(CACHE) as f:
        return json.load(f)


def wd_codes_for_lad(lad_code: str) -> set[str]:
    """Return the set of WD22CDs whose parent council is the given LAD22CD."""
    return {wd for wd, lad in load().items() if lad == lad_code}
