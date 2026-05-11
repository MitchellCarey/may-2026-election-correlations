# Repo notes for Claude

## Three pages, one stylesheet

The site has **three deployable HTML artifacts**, all served directly by GitHub Pages:

- [docs/index.html](docs/index.html) — "**Winners**" page. Census × who-won-each-ward correlations.
- [docs/changes.html](docs/changes.html) — "**Changes**" page. Census × who-flipped-each-ward correlations.
- [docs/map.html](docs/map.html) — "**Map**" page. Choropleth of the 215 GM wards: 2022/2021 winners, 2026 winners, and the seats that flipped.

They share styling via [docs/shared.css](docs/shared.css) (referenced from all three pages with `<link rel="stylesheet" href="shared.css">`) and a small cross-page `<nav class="pagenav">` block lets readers jump between them. There is **no build step in CI** — committed HTML is the deployment.

## Both pages are partially generated

Each page is hand-authored chrome (head, masthead, headlines, byline, section heads, footer) **plus** a single `<script>` block whose contents are spliced in by a build script:

```
// ===== BEGIN GENERATED — see scripts/07_build_artifact.py =====           (in index.html)
// ===== BEGIN GENERATED — see scripts/07b_build_changes_artifact.py =====   (in changes.html)
// ===== BEGIN GENERATED — see scripts/07c_build_map_artifact.py =====       (in map.html)
…
// ===== END GENERATED =====
```

`docs/index.html` also contains a separate generated SVG block from `08_parallel_chart.py` (different marker pair).

Everything **outside** the markers is hand-authored and preserved across builds. Everything **inside** is overwritten on every run.

### Where to make a change

| You want to change… | Edit here |
|---|---|
| Copy, headlines, captions, byline, methodology prose | `docs/index.html`, `docs/changes.html`, or `docs/map.html` (outside markers) |
| Page styling / fonts / layout | `docs/shared.css` (affects all three pages) |
| Shape of the rendered Winners data (RAW fields, labels, sort order, party colours) | `scripts/07_build_artifact.py`, then re-run it |
| Shape of the rendered Changes data | `scripts/07b_build_changes_artifact.py`, then re-run it |
| Shape of the rendered Map data (party colours, fuzzy-stroke marking, legend) | `scripts/07c_build_map_artifact.py`, then re-run it |
| Ward boundary geometry / projection / simplification | `scripts/09_fetch_ward_boundaries.py`, then re-run 07c |
| Underlying data (2026 winners, census, correlations, prior winners, flips) | upstream scripts, then re-run 07, 07b *and* 07c |

**Never hand-edit anything between the BEGIN/END markers.** Those edits will be wiped the next time anyone runs the build, and the diff is easy to miss in review.

## Keeping the artifacts current

Two parallel pipelines feed the two pages. Both are linear; only re-run from the earliest step that's actually stale.

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

Common cases:

- **Touched `scripts/0[1-6]_*.py` or input XLSX** → run that Winners script and every later one, ending with 07. If the change touches `all_wards.json`, also re-run `04b → 05b/05c → 06b → 07b` for Changes, and `07c` for Map (which reads the same downstream-of-04b file).
- **Touched `scripts/07_build_artifact.py`** → run 07 only.
- **Touched `scripts/0[145-7]b_*.py` or `05c_*.py`** → run from that script onwards through 07b. Also re-run 07c if `all_wards_with_prior.json` changed.
- **Touched `scripts/07c_build_map_artifact.py`** → run `07c --region=gm` and `07c --region=gb`.
- **Touched `scripts/09_fetch_ward_boundaries.py` or boundary set** → run `09 --force` then `07c --region=gm` and `07c --region=gb`.
- **Touched only copy/CSS in any of the three HTMLs** → no rebuild needed, but verify the BEGIN/END block didn't drift.

After any rebuild, `git diff docs/*.html` should only show changes inside the BEGIN/END markers (plus whatever you intentionally edited outside them). If unrelated chunks moved, something's wrong — investigate before committing.

## Before saying a task is done

1. If the task changed Winners data/scripts/renderer: confirm `07_build_artifact.py` ran cleanly and printed its summary line.
2. If the task changed Changes data/scripts/renderer: confirm `07b_build_changes_artifact.py` ran cleanly and printed its summary line.
3. If the task changed Map data/scripts/renderer: confirm `07c_build_map_artifact.py` ran cleanly for both `--region=gm` (must be 215/215 wards) and `--region=gb` (currently ~990 wards across the 69 registered councils). Less than the expected count for either region means the GSS join lost wards and needs investigation.
4. `git status` / `git diff docs/*.html` — make sure the spliced output is committed alongside the script changes (the deployed artifacts are the HTMLs, not the scripts; an un-rebuilt commit ships stale data).
5. If you only changed copy/CSS outside the markers, no rebuild is required — say so explicitly rather than running 07/07b/07c "just in case" (a no-op diff is fine, but skip the noise).

## Deployment

GitHub Pages serves the entire `docs/` directory from `main` directly — `docs/index.html`, `docs/changes.html`, and `docs/shared.css` all deploy as-is, no CI build step. The committed HTML *is* the deployment. This makes the "did you re-run 07/07b?" check load-bearing: a commit with updated data scripts but stale HTML will deploy stale numbers.

## Note on prior-winner data source

The Changes pipeline scrapes per-ward 2022/2021 winners from per-borough Wikipedia articles via `00_fetch_prior_winners.py` (cached in `data/source/wiki_*.json`). The original plan was to use the House of Commons Library annual XLSX handbooks, but `commonslibrary.parliament.uk` is behind a Cloudflare managed challenge that blocks programmatic clients. Wikipedia's per-ward `{{Election box winning candidate}}` templates are at least as easy to parse, and re-runs hit the cached files rather than re-fetching.
