# Repo notes for Claude

## Four pages, one stylesheet

The site has **four deployable HTML artifacts** per region, all served directly by GitHub Pages:

- [docs/index.html](docs/index.html) — "**Winners**" page. Census × who-won-each-ward correlations.
- [docs/changes.html](docs/changes.html) — "**Changes**" page. Census × who-flipped-each-ward correlations.
- [docs/map.html](docs/map.html) — "**Map**" page. Choropleth of the 215 GM wards: 2022/2021 winners, 2026 winners, and the seats that flipped.
- [docs/current.html](docs/current.html) — "**Current**" page. Choropleth of every ward painted by the most-recent winner, regardless of contest year. Where Map is May 2026 only, Current carries every council's last-contest result so the whole country can be coloured in one frame.

Each page has a Great Britain sibling under [docs/uk/](docs/uk/) with the same view applied country-wide.

They share styling via [docs/shared.css](docs/shared.css) (referenced from every page with `<link rel="stylesheet" href="shared.css">` or `"../shared.css"`) and a small cross-page `<nav class="pagenav">` block lets readers jump between Winners · Changes · Map · Current at either region. There is **no build step in CI** — committed HTML is the deployment.

## Both pages are partially generated

Each page is hand-authored chrome (head, masthead, headlines, byline, section heads, footer) **plus** a single `<script>` block whose contents are spliced in by a build script:

```
// ===== BEGIN GENERATED — see scripts/07_build_artifact.py =====                 (in index.html)
// ===== BEGIN GENERATED — see scripts/07b_build_changes_artifact.py =====         (in changes.html)
// ===== BEGIN GENERATED — see scripts/07c_build_map_artifact.py =====             (in map.html)
// ===== BEGIN GENERATED — see scripts/07d_build_current_map_artifact.py =====     (in current.html)
…
// ===== END GENERATED =====
```

`docs/index.html` also contains a separate generated SVG block from `08_parallel_chart.py` (different marker pair).

Everything **outside** the markers is hand-authored and preserved across builds. Everything **inside** is overwritten on every run.

### Where to make a change

| You want to change… | Edit here |
|---|---|
| Copy, headlines, captions, byline, methodology prose | `docs/index.html`, `docs/changes.html`, `docs/map.html`, or `docs/current.html` (outside markers) |
| Page styling / fonts / layout | `docs/shared.css` (affects every page) |
| Shape of the rendered Winners data (RAW fields, labels, sort order, party colours) | `scripts/07_build_artifact.py`, then re-run it |
| Shape of the rendered Changes data | `scripts/07b_build_changes_artifact.py`, then re-run it |
| Shape of the rendered Map data (party colours, fuzzy-stroke marking, legend) | `scripts/07c_build_map_artifact.py`, then re-run it |
| Shape of the rendered Current data (tooltip, year resolution, palette) | `scripts/07d_build_current_map_artifact.py`, then re-run it |
| Add a non-2026 council to the Current page | `data/source/councils.yaml` — append a row with `wiki_current_articles: [{year, title}, ...]`, then run 10 → 11 → 04c → 07d (both regions) |
| Ward boundary geometry / projection / simplification | `scripts/09_fetch_ward_boundaries.py`, then re-run 07c *and* 07d |
| Underlying data (2026 winners, census, correlations, prior winners, flips) | upstream scripts, then re-run 07, 07b, 07c *and* 07d |

**Never hand-edit anything between the BEGIN/END markers.** Those edits will be wiped the next time anyone runs the build, and the diff is easy to miss in review.

## Keeping the artifacts current

Four parallel pipelines feed the four pages. Each is linear; only re-run from the earliest step that's actually stale.

### Winners pipeline → `docs/index.html`

```
01_build_results.py          → data/all_results.json
02_match_gss.py              → data/all_gss_mapping.json
03_extract_census.py         → data/all_census.json     (needs data/source/*.xlsx)
04_consolidate.py            → data/all_wards.json
05_correlate.py              → data/correlations.json
06_prep_artifact_data.py     → data/v12_ward_data.json
07_build_artifact.py         → splices into docs/index.html
08_parallel_chart.py         → splices SVG into docs/index.html
```

### Changes pipeline → `docs/changes.html`

```
00_fetch_prior_winners.py    → data/source/wiki_*.json     (one-off; idempotent — skips cached files)
01b_extract_prior.py         → data/prior_winners.json
04b_join_prior.py            → data/all_wards_with_prior.json   (depends on data/all_wards.json)
05b_correlate_flips.py       → data/flip_correlations.json
05c_compute_before_after.py  → data/before_after.json
06b_prep_changes_data.py     → data/v1_changes_ward_data.json
07b_build_changes_artifact.py → splices into docs/changes.html
```

`05b` and `05c` both consume `all_wards_with_prior.json` and are independent of each other — they can run in either order.

The Changes pipeline depends on the Winners pipeline's `all_wards.json` — if upstream data changes, re-run `04` then `04b` (and everything downstream of each).

### Map pipeline → `docs/map.html` (and `docs/uk/map.html`)

```
09_fetch_ward_boundaries.py  → data/source/wd_may_2024_uk_bgc_gb.geojson  (cached raw fetch, ~50 MB, gitignored)
                             → data/ward_geoms.json                       (one-off; idempotent — skips if output exists, --force to rebuild)
07c_build_map_artifact.py [--region=gm|gb]
                             → splices into docs/map.html (gm) or docs/uk/map.html (gb)
                               (consumes ward_geoms.json + all_wards_with_prior.json)
```

`09` fetches every GB ward (~8,000) once and emits one `ward_geoms.json` containing per-region viewBoxes (`{gm: [...], gb: [...]}`); `07c` filters polygons + picks the viewBox for the requested region. `09` is build-only and depends on `geopandas`, `shapely`, `pyproj` (see `requirements.txt`). The deployed artifacts are just `docs/map.html` and `docs/uk/map.html` plus the JSON file; the geo deps don't ship.

### Current pipeline → `docs/current.html` (and `docs/uk/current.html`)

```
10_fetch_current_winners.py     → data/source/wiki_current_*.json   (one-off; idempotent — skips cached files)
11_extract_current.py           → data/current_winners_raw.json
04c_build_current_winners.py    → data/current_winners.json         (consumes all_wards.json + ward_geoms.json + raw scrape)
07d_build_current_map_artifact.py [--region=gm|gb]
                                → splices into docs/current.html (gm) or docs/uk/current.html (gb)
```

`10` walks `wiki_current_articles` in `data/source/councils.yaml` — a per-council list of `{year, title}` pairs in newest-first order. Councils that contested 2026 leave the field `null` (their winner is sourced from `all_wards.json`); non-2026 councils list every article needed for their per-seat last-contest coverage (one entry for all-out councils, 2-3 entries for thirds councils covering the years between their last all-out and now). `11` dispatches on `electoral_system` (`fptp` → `parse_article`, `stv` → `parse_stv_article` for Scottish councils). `04c` joins to WD24 names with the same two-pass match `07c` uses (normalised name + `ward_name_overrides.csv`); an optional `data/source/current_ward_overrides.csv` covers Welsh/Scottish pre-WD24 drift.

### Official-source pipeline (issue #9) → feeds 04c at higher priority than Wikipedia

```
12_fetch_official_results.py   → data/source/official_<slug>_<year>.{html|json|pdf}   (idempotent — skips cached files)
13_extract_official.py         → data/source/{county,ward}_official_<year>.csv         (appends rows from registered parsers; preserves hand-curated rows for councils without a parser)
04c_build_current_winners.py   → as above, with official rows outranking Wikipedia per-record
```

Each council in `councils.yaml` may declare `official_url` + `official_parser` + `official_year`. `12` fetches the URL (default GET; parser modules can override `fetch()` for Power BI etc.) into the cache. `13` dispatches on `official_parser` to `scripts/_official_parsers/<key>.py` and appends rows. CSV schemas: `lad_code,county,division,party,candidate,votes,source` for E10 counties; `lad_code,council,ward,party,candidate,votes,source` for everything else.

Parsers landed for Phase 2 of issue #9:
- `arcgis_dashboard` — Esri Election Results FeatureServer (East Sussex)
- `moderngov_per_division` — moderngov.co.uk per-division pages (West Sussex)
- `cmis_per_division` — DotNetNuke / OpenElection.net RDFa pages (Essex)
- Phase 1 hand-curated CSV pattern still in use for Norfolk (no parser yet)

Phase 2 deferrals (no `official_url` set, see comments on the registry rows):
- Suffolk — results only via Power BI embed; needs a DAX-query scraper or hand-curation
- Hampshire — hants.gov.uk Cloudflare-blocks programmatic clients; districts publish only their slices

Common cases:

- **Touched `scripts/0[1-6]_*.py` or input XLSX** → run that Winners script and every later one, ending with 07. If the change touches `all_wards.json`, also re-run `04b → 05b/05c → 06b → 07b` for Changes, `07c` for Map, and `04c → 07d` for Current (all three read downstream of `04`).
- **Touched `scripts/07_build_artifact.py`** → run 07 only.
- **Touched `scripts/0[145-7]b_*.py` or `05c_*.py`** → run from that script onwards through 07b. Also re-run 07c if `all_wards_with_prior.json` changed.
- **Touched `scripts/07c_build_map_artifact.py`** → run `07c --region=gm` and `07c --region=gb`.
- **Touched `scripts/10_*.py` / `11_*.py` / `04c_*.py`** → run from that script onwards through `07d --region=gm` and `07d --region=gb`.
- **Touched `scripts/12_*.py` / `13_*.py` or a module in `scripts/_official_parsers/`** → run `12` → `13` → `04c` → `07d --region=gm` → `07d --region=gb`. The fetcher and extractor are no-ops when no councils have `official_url` set, so a structural change without a registered council should leave `04c` output byte-identical.
- **Added an `official_url` / `official_parser` / `official_year` triple to a council in `data/source/councils.yaml`** → run `12` → `13` → `04c` → `07d` (both regions).
- **Touched `scripts/07d_build_current_map_artifact.py`** → run `07d --region=gm` and `07d --region=gb`.
- **Added rows or `wiki_current_articles` entries in `data/source/councils.yaml`** → run `10` → `11` → `04c` → `07d` (both regions). New rows with `wiki_2026` set also need `00b` and the Winners cascade.
- **Touched `scripts/09_fetch_ward_boundaries.py` or boundary set** → run `09 --force` then `07c --region=gm`, `07c --region=gb`, `07d --region=gm`, `07d --region=gb`.
- **Touched only copy/CSS in any of the four HTMLs** → no rebuild needed, but verify the BEGIN/END block didn't drift.

After any rebuild, `git diff docs/*.html` should only show changes inside the BEGIN/END markers (plus whatever you intentionally edited outside them). If unrelated chunks moved, something's wrong — investigate before committing.

## Before saying a task is done

1. If the task changed Winners data/scripts/renderer: confirm `07_build_artifact.py` ran cleanly and printed its summary line.
2. If the task changed Changes data/scripts/renderer: confirm `07b_build_changes_artifact.py` ran cleanly and printed its summary line.
3. If the task changed Map data/scripts/renderer: confirm `07c_build_map_artifact.py` ran cleanly for both `--region=gm` (must be 215/215 wards) and `--region=gb` (currently ~2,200 wards across the 134 registered councils). Less than the expected count for either region means the GSS join lost wards and needs investigation.
4. If the task changed Current data/scripts/renderer: confirm `07d_build_current_map_artifact.py` ran cleanly for both `--region=gm` (must be 215 wards; 214 with a winner + 1 grey for cancelled Bury · Moorside) and `--region=gb` (today's baseline is 7,934 GB ward-based wards with **7,898 winner-coloured + 36 grey** — the grey residual is the long tail from issue #7 phase D: ~26 WD24 wards in the six 2025-all-out boundary-review unitaries (Durham, Bucks, West/North Northamptonshire, Northumberland, Shropshire) where two pre-review wards merged into one new ward (the override schema is 1:1, so only one of each pair gets the proxy); ~8 Scottish wards where the 2022 article didn't cover every WD24 polygon; 1 cancelled Bury · Moorside; and 1 Runnymede ward absent from its 2023 article).
5. `git status` / `git diff docs/*.html` — make sure the spliced output is committed alongside the script changes (the deployed artifacts are the HTMLs, not the scripts; an un-rebuilt commit ships stale data).
6. If you only changed copy/CSS outside the markers, no rebuild is required — say so explicitly rather than running 07/07b/07c/07d "just in case" (a no-op diff is fine, but skip the noise).

## Deployment

GitHub Pages serves the entire `docs/` directory from `main` directly — `docs/index.html`, `docs/changes.html`, `docs/map.html`, `docs/current.html`, the `docs/uk/` mirrors, and `docs/shared.css` all deploy as-is, no CI build step. The committed HTML *is* the deployment. This makes the "did you re-run 07/07b/07c/07d?" check load-bearing: a commit with updated data scripts but stale HTML will deploy stale numbers.

## Note on prior-winner data source

The Changes pipeline scrapes per-ward 2022/2021 winners from per-borough Wikipedia articles via `00_fetch_prior_winners.py` (cached in `data/source/wiki_*.json`). The original plan was to use the House of Commons Library annual XLSX handbooks, but `commonslibrary.parliament.uk` is behind a Cloudflare managed challenge that blocks programmatic clients. Wikipedia's per-ward `{{Election box winning candidate}}` templates are at least as easy to parse, and re-runs hit the cached files rather than re-fetching.
