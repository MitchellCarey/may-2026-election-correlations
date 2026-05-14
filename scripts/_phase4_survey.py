"""One-off Phase 4 platform survey (issue #33).

Reads data/source/councils.yaml, filters to the 118 non-E10 councils that
contested 7 May 2026, and emits data/source/_phase4_survey.csv classifying
each council's results-publishing platform so issue #9 Phase 4 sub-issues
(#9-GM, #9-MG, #9-OTH, #9-BESP) can divide parser work without overlap.

This is a survey tool — not part of the build pipeline. The output CSV is
the deliverable. The script is committed for reproducibility and may need
re-running as councils publish (or move) their results pages.

Run:
    python3 scripts/_phase4_survey.py

By default it probes every council in YAML order, writing partial progress
to the CSV after each council so a Ctrl-C mid-run preserves work. Re-running
skips councils that already have a non-empty results_url in the existing
CSV (use --refresh to ignore the cache).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
COUNCILS_PATH = ROOT / "data" / "source" / "councils.yaml"
OUTPUT_CSV = ROOT / "data" / "source" / "_phase4_survey.csv"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "gm-2026-ward-analysis/phase4-survey (mitchellcarey2@gmail.com)"
)
TIMEOUT = 8.0


# Council name → gov.uk subdomain override. Anything not in this dict is
# auto-derived (lowercase, strip "Borough Council"/"Metropolitan"/etc., drop
# non-alphanumeric chars). These are the well-known initialisms or aliases
# where the auto-derivation gets it wrong.
SLUG_OVERRIDES: dict[str, str] = {
    "Hammersmith and Fulham": "lbhf",
    "Kingston upon Thames": "kingston",
    "Richmond upon Thames": "richmond",
    "Newcastle upon Tyne": "newcastle",
    "Kensington and Chelsea": "rbkc",
    "Barking and Dagenham": "lbbd",
    "Waltham Forest": "walthamforest",
    "Hackney": "hackney",
    "Tower Hamlets": "towerhamlets",
    "St. Helens": "sthelens",
    "King's Lynn and West Norfolk": "west-norfolk",
    "Stratford-on-Avon": "stratford",
    "Bristol, City of": "bristol",
    "Stoke-on-Trent": "stoke",
    "Cheshire West and Chester": "cheshirewestandchester",
    "Redcar and Cleveland": "redcar-cleveland",
    "Telford and Wrekin": "telford",
    "Windsor and Maidenhead": "rbwm",
    "Brighton and Hove": "brighton-hove",
    "Herefordshire, County of": "herefordshire",
    "Bath and North East Somerset": "bathnes",
    "Reading": "reading",
    "Wokingham": "wokingham",
    "West Berkshire": "westberks",
    "Milton Keynes": "milton-keynes",
    "Central Bedfordshire": "centralbedfordshire",
    "Blackburn with Darwen": "blackburn",
    "Stockton-on-Tees": "stockton",
    "Hartlepool": "hartlepool",
    "Three Rivers": "threerivers",
    "Mole Valley": "molevalley",
    "Tunbridge Wells": "tunbridgewells",
    "Brentwood": "brentwood",
    "Castle Point": "castlepoint",
    "Maldon": "maldon",
    "Rochford": "rochford",
    "Basildon": "basildon",
    "Tendring": "tendring",
    "Colchester": "colchester",
    "Epping Forest": "eppingforest",
    "Harlow": "harlow",
    "Burnley": "burnley",
    "Hyndburn": "hyndburn",
    "Pendle": "pendle",
    "Preston": "preston",
    "Rossendale": "rossendale",
    "South Ribble": "southribble",
    "West Lancashire": "westlancs",
    "Cherwell": "cherwell",
    "Oxford": "oxford",
    "Cambridge": "cambridge",
    "Watford": "watford",
    "Hertsmere": "hertsmere",
    "Broxbourne": "broxbourne",
    "Adur": "adur",
    "Worthing": "worthing",
    "Crawley": "crawley",
    "Eastleigh": "eastleigh",
    "Fareham": "fareham",
    "Gosport": "gosport",
    "Havant": "havant",
    "Rushmoor": "rushmoor",
    "Winchester": "winchester",
    "Basingstoke and Deane": "basingstoke",
    "Welwyn Hatfield": "welhat",
    "Tamworth": "tamworth",
    "Cannock Chase": "cannockchasedc",
    "Newcastle-under-Lyme": "newcastle-staffs",
    "West Oxfordshire": "westoxon",
    "South Cambridgeshire": "scambs",
    "North East Lincolnshire": "nelincs",
    "Isle of Wight": "iow",
    "Redditch": "redditchbc",
    "Mid Sussex": "midsussex",
    "Halton": "halton",
    "Warrington": "warrington",
    "Thurrock": "thurrock",
    "Southend-on-Sea": "southend",
    "Slough": "slough",
    "Plymouth": "plymouth",
    "Portsmouth": "portsmouth",
    "Southampton": "southampton",
    "Derby": "derby",
}


# Councils whose canonical results URL can't be derived from the auto-probe
# (joint councils, unusual subdomains, results buried in long URL paths).
# Each entry hand-pins the URL + platform discovered during the survey.
# Keyed by lad_code so re-running the script reproduces these rows verbatim.
MANUAL_OVERRIDES: dict[str, dict] = {
    "E08000030": {  # Walsall — go.walsall.gov.uk subdomain
        "results_url": "https://go.walsall.gov.uk/your-council/voting-and-elections/election/local-election-results-walsall-borough-2026/results",
        "platform": "bespoke",
        "http_status": 200,
        "page_form": "per-ward HTML",
        "notes": "per-ward subpages off /election/local-election-results-walsall-borough-2026/",
    },
    "E09000026": {  # Redbridge — my.redbridge.gov.uk subdomain
        "results_url": "https://my.redbridge.gov.uk/electionresults",
        "platform": "bespoke",
        "http_status": 200,
        "page_form": "single results HTML",
        "notes": "self-service portal subdomain",
    },
    "E09000028": {  # Southwark — buried URL path
        "results_url": "https://www.southwark.gov.uk/about-council/voting-and-elections/local-elections-2026/results-2026-local-elections",
        "platform": "bespoke",
        "http_status": 200,
        "page_form": "single results HTML",
        "notes": "",
    },
    "E08000019": {  # Sheffield — buried URL path
        "results_url": "https://www.sheffield.gov.uk/your-city-council/elections/local-elections-results-2026",
        "platform": "bespoke",
        "http_status": 200,
        "page_form": "single results HTML",
        "notes": "",
    },
    "E07000223": {  # Adur — joint council with Worthing
        "results_url": "https://www.adur-worthing.gov.uk/elections-and-voting/election-results/2026/",
        "platform": "bespoke",
        "http_status": 200,
        "page_form": "single results HTML",
        "notes": "joint Adur+Worthing portal; same URL as Worthing",
    },
    "E07000229": {  # Worthing — joint council with Adur
        "results_url": "https://www.adur-worthing.gov.uk/elections-and-voting/election-results/2026/",
        "platform": "bespoke",
        "http_status": 200,
        "page_form": "single results HTML",
        "notes": "joint Adur+Worthing portal; same URL as Adur",
    },
    "E06000046": {  # Isle of Wight — declaration PDF is the only structured source
        "results_url": "https://www.iow.gov.uk/media/3450/Declarations-of-Result/pdf/Isle_of_Wight_Council_Local_Election_Results_7_May_2026.pdf",
        "platform": "pdf_only",
        "http_status": 200,
        "page_form": "PDF",
        "notes": "council also has bespoke results article at /article/1179/Election-results but the PDF is the only per-ward source",
    },
    "E07000236": {  # Redditch — declaration PDFs per ward
        "results_url": "https://www.redditchbc.gov.uk/council/elections/current-elections-and-referendums/redditch-borough-council-elections-7-may-2026/",
        "platform": "pdf_only",
        "http_status": 200,
        "page_form": "PDF",
        "notes": "page links to per-ward declaration PDFs (e.g. central-declaration-of-results.pdf)",
    },
    "E07000177": {  # Cherwell — ModernGov on modgov subdomain (flaky probe)
        "results_url": "https://modgov.cherwell.gov.uk/mgManageElectionResults.aspx?bcr=1",
        "platform": "moderngov",
        "http_status": 200,
        "page_form": "per-ward HTML",
        "notes": "",
    },
    "E08000023": {  # South Tyneside — custom portal at portal.southtyneside.info
        "results_url": "https://portal.southtyneside.info/elections/LocalGovernment.aspx?id=47",
        "platform": "bespoke",
        "http_status": 200,
        "page_form": "per-ward HTML",
        "notes": "custom .info portal; www.southtyneside.gov.uk is Cloudflare-blocked but doesn't actually host results",
    },
    "E08000024": {  # Sunderland — single article URL behind Cloudflare
        "results_url": "https://www.sunderland.gov.uk/article/39917/Result-of-Poll-By-Ward-7-May-2026",
        "platform": "bespoke",
        "http_status": 200,
        "page_form": "single results HTML",
        "cloudflare": "true",
        "notes": "www.sunderland.gov.uk is Cloudflare-fronted; parser needs curl_cffi",
    },
    "E07000066": {  # Basildon — basildonmeetings.info ModernGov
        "results_url": "https://www.basildonmeetings.info/mgManageElectionResults.aspx?bcr=1",
        "platform": "moderngov",
        "http_status": 200,
        "page_form": "per-ward HTML",
        "notes": "ModernGov mounted on a .info vanity TLD",
    },
    "E06000010": {  # Kingston upon Hull — hullcc.gov.uk subdomain
        "results_url": "https://www.hullcc.gov.uk/egenda/akshullerps/election/index.html",
        "platform": "bespoke",
        "http_status": 200,
        "page_form": "single results HTML",
        "notes": "results in a static eGenda index frame",
    },
    "E06000012": {  # NE Lincolnshire — unusual URL path
        "results_url": "https://www.nelincs.gov.uk/north-east-lincolnshire-council-local-elections-2026/",
        "platform": "bespoke",
        "http_status": 200,
        "page_form": "single results HTML",
        "notes": "",
    },
    "E07000241": {  # Welwyn Hatfield — democracy.welhat.gov.uk is ModernGov,
                    # but the council's bespoke /election-results page is the
                    # canonical landing. democracy.welhat.gov.uk does work for
                    # ModernGov scraping if a parser prefers that route.
        "results_url": "https://democracy.welhat.gov.uk/mgManageElectionResults.aspx?bcr=1",
        "platform": "moderngov",
        "http_status": 200,
        "page_form": "per-ward HTML",
        "notes": "",
    },
}


@dataclass
class SurveyRow:
    lad_code: str
    council: str
    nation: str
    results_url: str = ""
    platform: str = "none_found"
    http_status: int = 0
    page_form: str = ""
    cloudflare: str = "false"
    notes: str = ""


def derive_slug(name: str) -> str:
    """Best-effort *.gov.uk subdomain derivation from a council name."""
    if name in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[name]
    s = name.lower()
    for suffix in (
        "metropolitan borough council",
        "london borough council",
        "borough council",
        "city council",
        "district council",
        "county council",
        " council",
        ", city of",
        ", county of",
    ):
        s = s.replace(suffix, "")
    # drop accents/punct, keep alpha only
    s = re.sub(r"[^a-z]+", "", s)
    return s


def http_get(url: str) -> tuple[int, str, bytes]:
    """Plain urllib GET. Returns (status, content_type, body[:64k])."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(65536)
            return r.status, r.headers.get("Content-Type", ""), body
    except urllib.error.HTTPError as e:
        try:
            body = e.read(65536)
        except Exception:
            body = b""
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", body
    except urllib.error.URLError as e:
        return 0, "", str(e).encode()
    except Exception as e:
        return 0, "", str(e).encode()


def detect_platform(url: str, body: bytes, content_type: str) -> tuple[str, str]:
    """Return (platform, page_form) per the survey detection rules."""
    url_l = url.lower()
    body_l = body[:65536].lower()

    moderngov_url = (
        ".moderngov.co.uk" in url_l
        or "mgelection" in url_l
        or "mgmanageelectionresults" in url_l
    )
    moderngov_body = (
        b"mgelectionarearesults.aspx" in body_l
        or b"mgmanageelectionresults" in body_l
        or b"mgcontentcommon.css" in body_l
        or b"modern.gov" in body_l
        or b"this site is powered by moderngov" in body_l
    )
    if moderngov_url or moderngov_body:
        return "moderngov", "per-ward HTML"
    if re.search(r"https?://cmis\.[^/]+\.gov\.uk/", url_l) or b"openelection:" in body_l:
        return "cmis", "per-ward HTML"
    if "services" in url_l and "arcgis.com" in url_l and "/featureserver/" in url_l:
        return "arcgis", "JSON"
    if "app.powerbi.com/view" in url_l or b"fixedclusteruri" in body_l:
        return "powerbi", "JSON"
    if "application/pdf" in content_type.lower() or url_l.endswith(".pdf"):
        return "pdf_only", "PDF"
    return "bespoke", "single results HTML"


def is_cloudflare(status: int, body: bytes) -> bool:
    if status != 403:
        return False
    b = body.lower()
    return (
        b"just a moment" in b
        or b"checking your browser" in b
        or b"cloudflare" in b
        or b"cf-error" in b
    )


def looks_like_results_page(body: bytes) -> bool:
    """Heuristic: does the body look like an election-results page?"""
    if not body:
        return False
    b = body.lower()
    # Common signals across election results pages.
    score = 0
    for needle in (b"election results", b"election result", b"ward results",
                   b"candidate", b"votes", b"declared", b"polling",
                   b"local election", b"council election"):
        if needle in b:
            score += 1
            if score >= 2:
                return True
    return False


def probe_council(council: dict) -> SurveyRow:
    """Try several URL patterns; return whichever classifies best."""
    name = council["name"]
    slug = derive_slug(name)
    row = SurveyRow(
        lad_code=council["lad_code"],
        council=name,
        nation=council.get("nation", "england"),
    )
    override = MANUAL_OVERRIDES.get(council["lad_code"])
    if override:
        for k, v in override.items():
            setattr(row, k, v)
        return row

    # ModernGov subdomain conventions vary wildly across councils. The
    # following patterns cover the cases observed during the survey: vanilla
    # `*.moderngov.co.uk`, plus the council-owned vanity domains that proxy
    # the same product (`democracy.*`, `modgov.*`, `meetings.*`,
    # `councillors.*`, `committees.*`, `moderngov.*`), plus the
    # `/Committees/mgManageElectionResults.aspx` path which some councils
    # mount directly on their main domain (RBKC, Southampton). We probe each
    # subdomain at the `mgManageElectionResults.aspx?bcr=1` path directly:
    # the root URL doesn't always render moderngov-flavored markers, but the
    # results-list page does, so this maximises detection hits.
    mg_path = "mgManageElectionResults.aspx?bcr=1"
    moderngov_candidates = [
        f"https://{slug}.moderngov.co.uk/{mg_path}",
        f"https://democracy.{slug}.gov.uk/{mg_path}",
        f"https://modgov.{slug}.gov.uk/{mg_path}",
        f"https://moderngov.{slug}.gov.uk/{mg_path}",
        f"https://meetings.{slug}.gov.uk/{mg_path}",
        f"https://councillors.{slug}.gov.uk/{mg_path}",
        f"https://committees.{slug}.gov.uk/{mg_path}",
        f"https://www.{slug}.gov.uk/Committees/{mg_path}",
        f"https://www.{slug}.gov.uk/moderngov/{mg_path}",
    ]
    bespoke_candidates = [
        f"https://cmis.{slug}.gov.uk/",
        f"https://{slug}.gov.uk/election-results",
        f"https://{slug}.gov.uk/elections-and-voting/election-results",
        f"https://{slug}.gov.uk/elections/results",
        f"https://{slug}.gov.uk/your-council/elections",
        f"https://www.{slug}.gov.uk/election-results",
        f"https://www.{slug}.gov.uk/elections",
        f"https://{slug}.gov.uk/elections",
        f"https://{slug}.gov.uk/electionresults",
        f"https://www.{slug}.gov.uk/electionresults",
    ]
    candidates = moderngov_candidates + bespoke_candidates

    best: Optional[SurveyRow] = None
    for url in candidates:
        status, ctype, body = http_get(url)
        cf = is_cloudflare(status, body)

        if status == 200:
            platform, page_form = detect_platform(url, body, ctype)
            # ModernGov / cmis / known platforms: take immediately.
            if platform in ("moderngov", "cmis", "arcgis", "powerbi", "pdf_only"):
                row.results_url = url
                row.platform = platform
                row.http_status = status
                row.page_form = page_form
                row.cloudflare = "true" if cf else "false"
                return row
            # bespoke landing page — only take it if it looks like results.
            if looks_like_results_page(body) and best is None:
                best = SurveyRow(
                    lad_code=row.lad_code,
                    council=row.council,
                    nation=row.nation,
                    results_url=url,
                    platform="bespoke",
                    http_status=200,
                    page_form="single results HTML",
                    cloudflare="true" if cf else "false",
                )
        elif cf and best is None:
            # Cloudflare-fronted page — record the URL but mark unknown
            # platform since we can't see the body.
            best = SurveyRow(
                lad_code=row.lad_code,
                council=row.council,
                nation=row.nation,
                results_url=url,
                platform="bespoke",
                http_status=403,
                page_form="",
                cloudflare="true",
                notes="cloudflare-blocked vanilla GET; needs curl_cffi to inspect",
            )

    return best or row


def load_existing_rows() -> dict[str, dict]:
    if not OUTPUT_CSV.exists():
        return {}
    out: dict[str, dict] = {}
    with open(OUTPUT_CSV) as f:
        # Skip comment lines (start with #) and header.
        reader = csv.DictReader(line for line in f if not line.startswith("#"))
        for r in reader:
            out[r["lad_code"]] = r
    return out


def write_rows(rows: list[SurveyRow], frequencies: Optional[dict] = None) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="") as f:
        if frequencies:
            f.write("# Phase 4 pattern survey - non-E10 councils that contested May 2026.\n")
            f.write("# See issue #33. Generated by scripts/_phase4_survey.py.\n")
            f.write("# Pattern frequencies:\n")
            for k in ("moderngov", "cmis", "arcgis", "powerbi", "bespoke", "pdf_only", "none_found"):
                f.write(f"#   {k:<12} {frequencies.get(k, 0)}\n")
            f.write(f"# Cloudflare-fronted (any platform): {frequencies.get('cloudflare', 0)}\n")
            f.write(f"# Total rows: {len(rows)}\n")
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "lad_code", "council", "nation", "results_url", "platform",
                "http_status", "page_form", "cloudflare", "notes",
            ],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-probe every council even if a row with a results_url exists.",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="Concurrent probe workers (default 8).",
    )
    parser.add_argument(
        "--only", default="",
        help="Comma-separated LAD codes to probe (default: all 118).",
    )
    args = parser.parse_args()

    with open(COUNCILS_PATH) as f:
        all_councils = yaml.safe_load(f)
    targets = [
        c for c in all_councils
        if c.get("wiki_2026") and not c["lad_code"].startswith("E10")
    ]
    wanted = (
        {x.strip() for x in args.only.split(",")} if args.only else None
    )
    print(f"targets: {len(targets)} councils", file=sys.stderr)

    existing = {} if (args.refresh and not wanted) else load_existing_rows()
    to_probe = []
    rows: list[SurveyRow] = []
    for c in targets:
        prior = existing.get(c["lad_code"])
        # With --only set, refresh only those councils; keep others cached.
        force_probe = wanted is not None and c["lad_code"] in wanted
        if prior and prior.get("results_url") and not force_probe:
            rows.append(SurveyRow(**{k: prior.get(k, "") for k in SurveyRow.__dataclass_fields__}))
        elif wanted is not None and c["lad_code"] not in wanted:
            # Not in --only set; keep cached row even if empty/none_found.
            if prior:
                rows.append(SurveyRow(**{k: prior.get(k, "") for k in SurveyRow.__dataclass_fields__}))
        else:
            to_probe.append(c)
    print(f"reusing {len(rows)} existing rows; probing {len(to_probe)}", file=sys.stderr)

    start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(probe_council, c): c for c in to_probe}
        done = 0
        for fut in as_completed(futures):
            row = fut.result()
            rows.append(row)
            done += 1
            print(
                f"  [{done:3}/{len(to_probe)}] {row.lad_code} {row.council[:30]:30} "
                f"{row.platform:10} {row.http_status} {row.results_url}",
                file=sys.stderr,
            )
            # Persist progress every 20 rows.
            if done % 20 == 0:
                rows.sort(key=lambda r: r.lad_code)
                write_rows(rows)
    elapsed = time.time() - start

    rows.sort(key=lambda r: r.lad_code)
    frequencies: dict[str, int] = {}
    for r in rows:
        frequencies[r.platform] = frequencies.get(r.platform, 0) + 1
        if r.cloudflare == "true":
            frequencies["cloudflare"] = frequencies.get("cloudflare", 0) + 1
    write_rows(rows, frequencies)
    print(f"\nwrote {len(rows)} rows in {elapsed:.1f}s to {OUTPUT_CSV.relative_to(ROOT)}", file=sys.stderr)
    print(f"frequencies: {frequencies}", file=sys.stderr)


if __name__ == "__main__":
    main()
