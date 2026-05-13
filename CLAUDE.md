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

`10` walks `wiki_current_articles` in `data/source/councils.yaml` — a per-council list of `{year, title}` pairs in newest-first order. Councils that contested 2026 leave the field `null` (their winner is sourced from `all_wards.json`); non-2026 councils list every article needed for their per-seat last-contest coverage (one entry for all-out councils, 2-3 entries for thirds councils covering the years between their last all-out and now). `11` dispatches on `electoral_system` (`fptp` → `parse_article`, `stv` → `parse_stv_article` for Scottish councils). `04c` joins to WD24 names with the same two-pass match `07c` uses (normalised name + `ward_name_overrides.csv`); an optional `data/source/current_ward_overrides.csv` covers Welsh/Scottish pre-WD24 drift and the 2025-all-out boundary-review unitaries (Durham, Bucks, W/N Northamptonshire, Northumberland, Shropshire). Multiple rows may share a `scraped_name` — each row paints one additional WD24 polygon absorbed by that post-review ward, so a 2025 ward that swallowed two pre-review WD24 wards gets two rows.

### Senedd 2026 overlay pipeline (issue #20) → feeds the GB current map only

```
14_fetch_senedd_results.py     → data/source/wiki_senedd_*_2026.json  (idempotent — skips cached files)
15_extract_senedd.py           → data/senedd_2026.json                (16 records: code, name, plurality_party, year, seats, votes)
16_fetch_senedd_geoms.py       → data/senedd_geoms.json               (16 SVG paths sharing the gb viewBox; raw cache at data/source/senedd_final_2026.geojson)
07d_build_current_map_artifact.py → consumes the two outputs and emits SENEDD / SENEDD_PATHS arrays
```

The 16 new Senedd constituencies don't map 1:1 to councils, so the registry lives at `scripts/_senedd_constituencies.py` (synthetic codes `S01..S16` because ONS hasn't shipped an SPC_MAY_2026 lookup yet) and is shared between `14`/`15`/`16`. `15` derives the 6-seat split per constituency from the "Members of the Senedd" table in each per-constituency Wikipedia article (uniform anchor across all 16; the elected-marker conventions inside the per-party Election box rows diverge between Bangor-style `(E)` and Blaenau-style `(elected N)` and Brycheiniog-style no-marker, so we don't rely on them). `16` fetches the DataMapWales GeoServer WFS layer `geonode:senedd_final_2026` in EPSG:27700 GeoJSON, simplifies at 100 m, and re-applies the same y-flip 09 used (bounds re-discovered by scanning ward path integers in `ward_geoms.json`) so Senedd polygons overlay the wards in the same SVG coord space. `07d` only loads the two Senedd JSONs on `--region=gb`; the GM page is byte-identical with or without them.

### GE 2024 overlay pipeline (issue #26) → feeds the GB current map only

```
19_fetch_ge2024_results.py    → data/source/wiki_ge2024_*.json   (idempotent — skips cached files; ~650 fetches, ~5–6 min one-off)
20_extract_ge2024.py          → data/ge2024.json                 (650 records: code, name, winner_party, candidate, year=2024, votes)
21_fetch_pcon_geoms.py        → data/pcon_geoms.json             (650 SVG paths sharing the gb viewBox; raw cache at data/source/pcon_jul_2024.geojson)
07d_build_current_map_artifact.py → consumes both outputs and emits PCON / PCON_PATHS arrays on --region=gb, filtering 650 → 632 GB seats at render time
```

The registry lives at `scripts/_ge2024_constituencies.py` and uses real ONS `PCON_JUL_2024` codes (`E14001063`, …) sourced from the `PCON_2024_UK_NC_v2` lookup on the ONS Open Geography Portal. `20` reuses `_wiki_parser.normalize_party` with a thin Westminster-specific wrapper to preserve "Speaker" (Lindsay Hoyle, Chorley) as its own party label rather than collapsing to "Other"; the matching palette entry lives in `_artifact_lib.PARTY_COLOURS_MAP` so 07c and 07d both pick it up. `21` fetches `Westminster_Parliamentary_Constituencies_July_2024_Boundaries_UK_BGC` from ONS in EPSG:27700, simplifies at 100 m, and re-applies the same y-flip 09 used (bounds re-discovered from `ward_geoms.json` exactly as `16` does for Senedd) so PCON polygons share the SVG coord space with wards, boroughs, CEDs, Holyrood and Senedd.

NI (18 N05 seats) is fetched on disk but **filtered out at render time** in `07d` because the `gb` viewBox excludes NI — option 1 in the issue. The `view=recent` z-order is strict chronological: PCON 2024 sits below CED 2025 and the 2026 devolved layers, but above older ward colours where no other layer overlaps. The dedicated `view=pcon` button isolates the 632-seat layer when the reader explicitly asks for it. `07d` only loads the two GE 2024 JSONs on `--region=gb`; the GM page emits empty `PCON` / `PCON_PATHS` arrays and remains byte-identical to today's render.

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
- `powerbi_dashboard` — Power BI publish-to-web DAX scraper (Suffolk)
- Phase 1 hand-curated CSV pattern still in use for Norfolk (no parser yet)

Phase 2 deferrals (no `official_url` set, see comments on the registry rows):
- Hampshire — hants.gov.uk Cloudflare-blocks programmatic clients; districts publish only their slices

For counties where the 2025/2026 LGBCE review redrew divisions, `scripts/09c_overlay_lgbce_ceds.py` replaces the pre-review CED25 polygons in `data/ward_geoms.json` with post-review polygons sourced from each county's LGBCE final-recommendation shapefile (Norfolk, Essex, Suffolk today). The shapefile zips cache under `data/source/lgbce/` and are fetched idempotently. Spelling differences between LGBCE and the council's published CSV are reconciled by the `NAME_FIXES` map at the top of `09c`.

As a fallback for any future county where we have results but no post-review polygons, `04c` also consults `data/source/ced_name_overrides.csv` (schema: `cty_code,ons_name,csv_division,note`) — geometry-side → result-side, mirroring `ward_name_overrides.csv`. Currently empty for Norfolk/Essex/Suffolk because the LGBCE overlay handles them; reserved for future counties.

Common cases:

- **Touched `scripts/0[1-6]_*.py` or input XLSX** → run that Winners script and every later one, ending with 07. If the change touches `all_wards.json`, also re-run `04b → 05b/05c → 06b → 07b` for Changes, `07c` for Map, and `04c → 07d` for Current (all three read downstream of `04`).
- **Touched `scripts/07_build_artifact.py`** → run 07 only.
- **Touched `scripts/0[145-7]b_*.py` or `05c_*.py`** → run from that script onwards through 07b. Also re-run 07c if `all_wards_with_prior.json` changed.
- **Touched `scripts/07c_build_map_artifact.py`** → run `07c --region=gm` and `07c --region=gb`.
- **Touched `scripts/10_*.py` / `11_*.py` / `04c_*.py`** → run from that script onwards through `07d --region=gm` and `07d --region=gb`.
- **Touched `scripts/12_*.py` / `13_*.py` or a module in `scripts/_official_parsers/`** → run `12` → `13` → `04c` → `07d --region=gm` → `07d --region=gb`. The fetcher and extractor are no-ops when no councils have `official_url` set, so a structural change without a registered council should leave `04c` output byte-identical.
- **Added an `official_url` / `official_parser` / `official_year` triple to a council in `data/source/councils.yaml`** → run `12` → `13` → `04c` → `07d` (both regions).
- **Added or edited a row in `data/source/ced_name_overrides.csv`** → run `04c` → `07d` (both regions). The override boosts `matched` in 04c's summary line; check the per-county counts to confirm the new row landed where you expected.
- **Added a county to `scripts/09c_overlay_lgbce_ceds.py` (new LGBCE shapefile)** → run `09c --force` → `04c` → `07d` (both regions). Confirm the per-county count is 100 % (or notes the gap if a specific division has no result).
- **Touched `scripts/07d_build_current_map_artifact.py`** → run `07d --region=gm` and `07d --region=gb`.
- **Added rows or `wiki_current_articles` entries in `data/source/councils.yaml`** → run `10` → `11` → `04c` → `07d` (both regions). New rows with `wiki_2026` set also need `00b` and the Winners cascade.
- **Touched `scripts/14` / `15` / `16` or `scripts/_senedd_constituencies.py`** → run from that script onwards through `07d --region=gm` and `07d --region=gb`. The GM page is gated on `region == 'gb'` and will produce a byte-identical diff.
- **Touched `scripts/19` / `20` / `21` or `scripts/_ge2024_constituencies.py`** → run from that script onwards through `07d --region=gm` and `07d --region=gb`. GM is byte-identical (PCON gated on `region == 'gb'`, like Senedd).
- **Touched `scripts/09_fetch_ward_boundaries.py` or boundary set** → run `09 --force` then `07c --region=gm`, `07c --region=gb`, `07d --region=gm`, `07d --region=gb`. The Senedd y-flip in `16` reads bounds from `ward_geoms.json`, so re-run `16 --force` too if 09's bounds shift.
- **Touched only copy/CSS in any of the four HTMLs** → no rebuild needed, but verify the BEGIN/END block didn't drift.

After any rebuild, `git diff docs/*.html` should only show changes inside the BEGIN/END markers (plus whatever you intentionally edited outside them). If unrelated chunks moved, something's wrong — investigate before committing.

## Before saying a task is done

1. If the task changed Winners data/scripts/renderer: confirm `07_build_artifact.py` ran cleanly and printed its summary line.
2. If the task changed Changes data/scripts/renderer: confirm `07b_build_changes_artifact.py` ran cleanly and printed its summary line.
3. If the task changed Map data/scripts/renderer: confirm `07c_build_map_artifact.py` ran cleanly for both `--region=gm` (must be 215/215 wards) and `--region=gb` (currently ~2,200 wards across the 134 registered councils). Less than the expected count for either region means the GSS join lost wards and needs investigation.
4. If the task changed Current data/scripts/renderer: confirm `07d_build_current_map_artifact.py` ran cleanly for both `--region=gm` (must be 215/215 wards) and `--region=gb` (today's baseline is 7,934 GB ward-based wards with **7,925 winner-coloured + 9 grey** — the grey residual after issue #7: 8 Scottish wards where the 2022 STV article didn't cover every WD24 polygon (Highland, Inverclyde, Moray, Na h-Eileanan Siar, Shetland), and 1 Runnymede ward absent from its 2023 article. Both buckets are deferred to issue #9 phase 5 official-source backfill. The 2025-all-out boundary-review unitaries (Durham, Bucks, West/North Northamptonshire, Northumberland, Shropshire) closed when `current_ward_overrides.csv` was extended to N:1 mappings — one post-review scraped ward can now paint every pre-review WD24 polygon it absorbed.). The GB run should also log `senedd in gb: 16 (with winner: 16; grey: 0)`, `pcon in gb: 632 (with winner: 632; grey: 0)`, and `15`'s summary should read `16/16 constituencies, 96/96 seats accounted for`.
5. `git status` / `git diff docs/*.html` — make sure the spliced output is committed alongside the script changes (the deployed artifacts are the HTMLs, not the scripts; an un-rebuilt commit ships stale data).
6. If you only changed copy/CSS outside the markers, no rebuild is required — say so explicitly rather than running 07/07b/07c/07d "just in case" (a no-op diff is fine, but skip the noise).

## Deployment

GitHub Pages serves the entire `docs/` directory from `main` directly — `docs/index.html`, `docs/changes.html`, `docs/map.html`, `docs/current.html`, the `docs/uk/` mirrors, and `docs/shared.css` all deploy as-is, no CI build step. The committed HTML *is* the deployment. This makes the "did you re-run 07/07b/07c/07d?" check load-bearing: a commit with updated data scripts but stale HTML will deploy stale numbers.

## Note on prior-winner data source

The Changes pipeline scrapes per-ward 2022/2021 winners from per-borough Wikipedia articles via `00_fetch_prior_winners.py` (cached in `data/source/wiki_*.json`). The original plan was to use the House of Commons Library annual XLSX handbooks, but `commonslibrary.parliament.uk` is behind a Cloudflare managed challenge that blocks programmatic clients. Wikipedia's per-ward `{{Election box winning candidate}}` templates are at least as easy to parse, and re-runs hit the cached files rather than re-fetching.
