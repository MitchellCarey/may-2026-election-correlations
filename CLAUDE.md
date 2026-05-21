# Repo notes for Claude

## Data accuracy is paramount

Every change that touches an election-data pipeline must use the **most authoritative primary source available**. Wikipedia is a useful cross-check, never the primary source where an official one exists.

**Source hierarchy (highest → lowest authority):**

1. **Returning officer / council publication** — direct from the body that ran the election. Already used by the official-source pipeline (`12` / `13`) for 2026 local results; the same principle applies retrospectively.
2. **Electoral Commission / House of Commons Library** — authoritative compilations cross-checked against returning officers. Phase 1E (#71) uses HoC Library CBP-8647 (1918-2019 GE results) as the primary source for the historical Westminster slider. `commonslibrary.parliament.uk` is Cloudflare-gated, but `scripts/_official_parsers/_cloudflare.py::cloudflare_session()` (curl_cffi Chrome impersonation) bypasses the challenge — the older "HoC Library is blocked" note in this file is obsolete.
3. **ONS Open Geography Portal** — boundary geometry + code lookups. Already the primary source for every polygon pipeline (`09` / `09c` / `09d` / `09e` / `09f` / `16` / `16b` / `21` / `21b`).
4. **Wikipedia** — fallback / cross-check only. When dual-sourcing alongside an official source, log per-record conflicts to stderr and prefer the official value (pattern: surface silent join failures).

When changing any pipeline that today uses Wikipedia as the primary source, evaluate whether an official source has become available, and migrate if so. Particularly: the Changes pipeline's `00_fetch_prior_winners.py` / `01b_extract_prior.py` (today Wikipedia-only) could be upgraded to HoC Library local-election handbooks now that the Cloudflare bypass exists — separate piece of work, but flag if touched.

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
11_extract_current.py           → data/current_winners_raw.json     (calls _wiki_history.iter_council_year_records,
                                                                      collapses to newest-per-ward)
04c_build_current_winners.py    → data/current_winners.json         (consumes all_wards.json + ward_geoms.json + raw scrape)
04d_build_ward_history.py       → data/ward_history.json            (sibling of 04c — keeps full per-year history;
                                                                      drives the time slider on the GB current page,
                                                                      issue #70 / #69 phase 1A)
04e_build_ced_history.py        → data/ced_history.json             (sibling of 04d — per-CED per-year history for
                                                                      the county-tier slider repaint, issue #69 phase 1B
                                                                      / #73; consumes `ceds` + `ceds_pre_review` from
                                                                      ward_geoms.json so post-review LGBCE polygons and
                                                                      pre-review PRE_ polygons each receive results from
                                                                      the years they were the legal-effect boundaries)
07d_build_current_map_artifact.py [--region=gm|gb]
                                → splices into docs/current.html (gm) or docs/uk/current.html (gb).
                                  On --region=gb, additionally splices `YEARS` + `WARD_HISTORY` constants and the
                                  slider/playback JS block, plus (phase 1B) `CED_PATHS_PRE` + `CED_ERAS` + `CED_HISTORY`
                                  for era-aware CED repaint. GM artifact carries empty CED_PATHS_PRE / CED_ERAS for
                                  shared-renderer consistency but renders identically with or without those constants.
```

`10` walks `wiki_current_articles` in `data/source/councils.yaml` — a per-council list of `{year, title}` pairs in newest-first order. Councils that contested 2026 leave the field `null` (their winner is sourced from `all_wards.json`); non-2026 councils list every article needed for their per-seat last-contest coverage (one entry for all-out councils, 2-3 entries for thirds councils covering the years between their last all-out and now). As part of phase 1A of the time slider (issue #70) the historical-year coverage was expanded back to 2018 across all in-scope GB councils, so every council now lists every contest year from 2018 through 2025 it had (skipping 2020 which was deferred under the Coronavirus postponement regulations). Phase 1B (#73) extended the county-tier (E10) coverage back to 2017 — all 21 in-scope English counties now carry 2017 + 2021 entries (Worcestershire already had them; the rest were added in PR #76). `11` dispatches on `electoral_system` (`fptp` → `parse_article`, `stv` → `parse_stv_article` for Scottish councils) via the shared `scripts/_wiki_history.iter_council_year_records` helper. `04c` joins to WD24 names with the same two-pass match `07c` uses (normalised name + `ward_name_overrides.csv`); an optional `data/source/current_ward_overrides.csv` covers Welsh/Scottish pre-WD24 drift and the 2025-all-out boundary-review unitaries (Durham, Bucks, W/N Northamptonshire, Northumberland, Shropshire). Multiple rows may share a `scraped_name` — each row paints one additional WD24 polygon absorbed by that post-review ward, so a 2025 ward that swallowed two pre-review WD24 wards gets two rows. `04d` reuses 04c's helpers + the same `_wiki_history` walker but keeps every year (no first-write-wins collapse), emitting `{years, wards: {gss: {borough, ward, history: [{y, w, src, url}]}}}` — each history entry carries the source URL (Wikipedia article or council results page) so the slider tooltip can let readers click through to verify accuracy. `04e` is the CED-side sibling — same three-pass shape (county_official CSV → wiki_2026 → iter_council_year_records) but iterates polygons (both `ceds` and `ceds_pre_review`) so a Norfolk 2017 record routes to the matching `PRE_E10000020_*` key, never the `LGBCE_E10000020_*` key, and the 17 unchanged counties keep their bare CED25CD keys for all four county-contest years.

### Pre-review CED polygons (issue #69 phase 1B) → feeds the GB current historical slider

```
09e_overlay_pre_review_ceds.py → data/ward_geoms.json `ceds_pre_review` key   (sibling of 09c)
04e_build_ced_history.py       → data/ced_history.json                         (sibling of 04d)
07d_build_current_map_artifact.py → consumes both on --region=gb; emits CED_PATHS_PRE / CED_ERAS / CED_HISTORY
```

`09e` produces 298 `PRE_<cty>_<slug>` polygons for the four counties whose 2017+2021 boundaries differ from `ceds`'s current era: Norfolk (84), Essex (70), Suffolk (63), Surrey (81). Norfolk/Essex/Suffolk's pre-review polygons are 09c's "before" state — fetched fresh from ONS `CED_MAY_2025` because 09c REPLACES those entries with LGBCE post-review polygons. Surrey's pre-abolition polygons come from the same CED25 dataset (Surrey CC is abolished after May 2026, so its 81 divisions don't appear in the post-2026 era); 09e also strips Surrey's CED25 entries from `ceds` so 07d's era logic distinguishes the four counties cleanly. The renderer in 07d stamps each `path.ced` with `data-era` ('post' for `LGBCE_*`, 'pre' for `PRE_*`, 'any' for bare CED25CDs) and `paintAtYear` toggles inline `display:none` based on slider year (`pre → y < 2026`, `post → y >= 2026`, `any → always`). Carry-forward fills come from `CED_HISTORY[key].history` using the same "newest entry with y <= targetYear" rule as ward history.

### Pre-review Holyrood polygons (issue #69 phase 1C / #74) → feeds the GB current historical slider

```
09f_overlay_pre_review_holyrood.py → data/ward_geoms.json `spcs_pre_review` key  (sibling of 09e)
17b_fetch_holyrood_history.py      → data/source/wiki_holyrood_constituency_<SPC22CD>.json (sibling of 17; per-constituency)
18b_extract_holyrood_history.py    → data/holyrood_history_raw.json              (sibling of 18; reuses normalize_party)
04f_build_holyrood_history.py      → data/holyrood_history.json                  (sibling of 04e)
07d_build_current_map_artifact.py  → consumes spcs_pre_review + holyrood_history on --region=gb;
                                     emits HOLYROOD_PATHS_PRE / HOLYROOD_ERAS / HOLYROOD_HISTORY
```

`09f` fetches ONS `SPC_DEC_2022_SC_BGC` (the 2014 73-constituency set in legal effect at the 2016 and 2021 elections) and emits 73 `PRE_<SPC22CD>` polygons under a new `spcs_pre_review` key. SPC22 codes (S16000074-S16000150) are disjoint from SPC26 codes (S16000151-S16000223), so `PRE_` prefix + bare key uniqueness is preserved. Unlike Surrey CEDs in 09e, Holyrood 2026 is contested under the new boundaries — 09d's `spcs` is untouched.

`17b` walks the 73-row `scripts/_holyrood_constituencies.py` registry (SPC22CD + name + electoral region + Wikipedia article title) and fetches each per-constituency article. One fetch per constituency yields every contest year via the `{{AMS election box}}` template family; the issue's "~146" estimate overcounts. Two non-standard wiki titles: Orkney at "Orkney Islands (constituency)" (no "Scottish Parliament" qualifier), Shetland at "Shetland Islands (Scottish Parliament constituency)".

`18b` parses the AMS election boxes (post-2007 Holyrood convention) — brace-aware body scanning so nested templates like `{{increase}}1.7` inside a candidate row don't truncate the match. Winner detection prefers the row-level `|winner = yes` marker and falls back to the tail `{{AMS election box {win,hold,gain}}}` template. Coverage: 73/73 at 2016, 72/73 at 2021. The one gap (Perthshire North 2021 — Wikipedia article skips from the 2026 box straight to 2016) is filled by `data/source/holyrood_official_2021.csv`, mirroring Phase 1B's `county_official_<year>.csv` pattern. The CSV is consumed by 04f at the highest pass rank so a future Wikipedia edit doesn't downgrade the curated value silently.

`04f` is the Holyrood-side sibling of `04e`. `SLIDER_YEARS = [2016, 2021, 2026]`; `polygon_accept_years()` routes 2016 and 2021 records to `PRE_<SPC22CD>` keys and 2026 records to bare `S16000***` keys. Three passes: per-constituency wiki for 2016+2021 (18b output), consolidated wiki for 2026 (holyrood_winners.json from 18), then optional `holyrood_official_<year>.csv` hand-curation as the last word per (polygon, year). Source URLs are the per-constituency Wikipedia article (for 2016/2021) and the consolidated 2026 results article — they survive into HOLYROOD_HISTORY and drive the click-to-source behaviour in 07d.

07d stamps each `path.holyrood` with `data-spc` and `data-era` ('pre' for `PRE_*`, 'post' for bare SPC codes — there's no 'any' analogue: a Holyrood polygon is either pre-review or post-review, never both eras). `paintAtYear`'s `path.holyrood` block mirrors the existing `path.ced` block exactly. The renderer's `HOLYROOD.map(...)` lookup picks `HOLYROOD_PATHS[h.spc] || HOLYROOD_PATHS_PRE[h.spc]` so a single `h.spc` field reaches either polygon set. The 73 synthetic PRE_ holyrood_js entries carry initial `{w: null, y: null}` so they paint grey until paintAtYear fills them at slider time.

The slider's `YEARS` array is now the union of ward / CED / Holyrood year stops (10 stops total: `[2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]`). Wards have no 2016 contests; carry-forward in paintAtYear handles the gap (wards show their nearest-prior winner at year=2016, typically a 2012 or older result that isn't in WARD_HISTORY — they paint grey).

### Pre-review Senedd polygons (issue #69 phase 1D / #72) → feeds the GB current historical slider

```
16b_fetch_senedd_2007_geoms.py → data/senedd_geoms_2007.json (40-constituency NAWC21 boundary set; sibling of 16)
14b_fetch_senedd_history.py    → data/source/wiki_senedd_constituency_<NAWC21CD>.json   (per-constituency × 40)
                               → data/source/wiki_senedd_region_<slug>.json             (per-region × 5)
15b_extract_senedd_history.py  → data/senedd_history_raw.json   (sibling of 18b; FPTP + regional-list parser)
04g_build_senedd_history.py    → data/senedd_history.json       (sibling of 04f; per-constituency + per-region)
07d_build_current_map_artifact.py → consumes senedd_geoms_2007 + senedd_history on --region=gb;
                                    emits SENEDD_PATHS_PRE / SENEDD_ERAS / SENEDD_HISTORY +
                                    SENEDD_REGION_HISTORY / SENEDD_RAW_DISPLAY (for the regional-list tooltip)
```

`16b` fetches ONS `NAWC_DEC_2021_WA_BGC_V3` (the 40-constituency set in legal effect at the 2011, 2016 and 2021 elections — Welsh Assembly Constituencies were last reviewed in 2006, so the December 2021 snapshot is the original 2007 boundaries used at all three pre-2026 contests). Emits 40 polygons keyed by NAWC21CD into a standalone `data/senedd_geoms_2007.json` (NOT into `ward_geoms.json` — Senedd 2026 geometry also lives in its own file at `data/senedd_geoms.json`, so the pre-review set follows the same external-file pattern rather than the inline `spcs_pre_review` pattern Holyrood uses).

`14b` walks the 40-row + 5-row `scripts/_senedd_constituencies_2007.py` registry (NAWC21CD + name + Wikipedia title + electoral region for constituencies; region name + Wikipedia title for the 5 PR regions). Each Welsh constituency article (uniform `"<Name> (Senedd constituency)"` pattern) covers every contest year via `{{AMS election box ...}}` templates; each region article (uniform `"<Region> (Senedd electoral region)"`) carries `===Regional MSs/AMs elected in YYYY===` sections per year. One fetch per article — 45 fetches total, not the 80-90 the issue estimated.

`15b` reuses 18b's brace-aware candidate-row scanner with two Welsh-specific adjustments: (1) end-template alternation accepts both `{{AMS election box end}}` (2021 form) and plain `{{Election box end}}` (pre-2021 form, which covers the 2011 box on every constituency); (2) tail-winner regex matches `{{Election box {hold,gain} with party link}}` instead of Holyrood's `{{AMS election box win|hold|gain}}`. A `parse_regional_list` helper scans each region article's per-year wikitable for `bgcolor={{party color|<PartyName>}}` markers (tolerant of optional quoting around the template) and counts parties; each regional record carries both `seats` (normalised labels) and `seats_raw` (raw Wikipedia party strings — e.g. "UK Independence Party", "Welsh Labour") so the tooltip can render historical accuracy where normalize_party would otherwise flatten UKIP-style wins to "Other". Coverage: 40/40 constituencies × 3 years (2011, 2016, 2021), 5/5 regions × 3 years × 4 list seats = 20/20 seats per year. 2011 has zero UKIP regional-list seats (UKIP first won list seats in Wales at 2016); 2011's regional split is dominated by Conservative + Plaid Cymru gains as the Welsh Liberal Democrats collapsed.

`04g` is the Senedd-side sibling of `04f`. `SLIDER_YEARS = [2011, 2016, 2021, 2026]` (2011 added in #80). Four passes: per-constituency wiki for 2011+2016+2021 (15b output, kind="fptp") routes to `PRE_<NAWC21CD>` keys; consolidated wiki for 2026 (senedd_2026.json from 15) routes to bare S0x keys; optional `senedd_official_<year>.csv` hand-curation (currently empty — landed as a future pattern); then a fourth pass for region records (kind="regional") into a parallel `regions` block. Output schema: `{years, constituencies: {polygon_key: {name, region, history: [...]}}, regions: {<region>: {history: [{y, seats, seats_raw, src, url}]}}}`.

07d stamps each `path.senedd` with `data-senedd` (the polygon key — bare S0x or `PRE_<NAWC21CD>`) and `data-era` ('pre' for `PRE_*`, 'post' for bare S0x — no 'any' analogue, mirroring Holyrood). `paintAtYear`'s `path.senedd` block mirrors the existing `path.holyrood` block, with one wrinkle: tooltip rewrite is **skipped for era=post** so the rich 6-seat split that `fmtSeneddTitle` produces at initial render survives slider ticks (Senedd 2026 uses closed-list PR per constituency, so seat splits matter; Holyrood 2026 is FPTP, so the rewrite is a strict improvement there). For era=pre, the rewrite appends a regional-list line: "Regional list 2021: Lab 2, Plaid 1, Con 1" via carry-forward through `SENEDD_REGION_HISTORY[<region>].history`, preferring `seats_raw` (with `SENEDD_RAW_DISPLAY` shortening "Welsh Labour" → "Lab", "UK Independence Party" → "UKIP", etc.) over the normalised `seats` dict.

The 40 synthetic PRE_ senedd_js entries carry initial `{w: null, y: null, seats: {}, votes: {}}` so they paint grey until paintAtYear fills them at slider time. The CSS rule `.map-svg.slider-pre-2026 path.senedd` (which previously hid all Senedd at year < 2026) was removed in Phase 1D since paintAtYear's inline `style.display` now manages era-based visibility — same architectural shift CEDs and Holyrood went through in phases 1B / 1C. Phase 1D adds no new slider year stops; 2016 + 2021 are already in the union via Holyrood. **#80 extension:** adding 2011 introduces a new slider tick — `SLIDER_YEARS` in 04g grows to `[2011, 2016, 2021, 2026]`, and the union in 07d picks 2011 up automatically. At year=2011 only Senedd polygons carry a winner; wards / CEDs / PCONs / Holyrood carry-forward through paintAtYear, and most paint grey because their history floors are higher (Holyrood starts 2016; PCON 2015; ward / CED 2017+).

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

### Pre-review Westminster polygons (issue #69 phase 1E / #71) → feeds the GB current historical slider

```
21b_fetch_pcon_2010_geoms.py    → data/pcon_geoms_2010.json    (650 SVG paths in the GB viewBox coord space; raw cache at data/source/pcon_dec_2021.geojson)
19b_fetch_ge_history.py         → data/source/hoc_ge_1918_2019_by_pcon.xlsx + .csv  (HoC Library CBP-8647; idempotent; fetched via _cloudflare.py)
20b_extract_ge_history.py       → data/ge_history.json         (650 PCONs × 4 years = 2,600 PCON-years from the HoC XLSX; per-record schema mirrors holyrood_history.json / senedd_history.json)
07d_build_current_map_artifact.py → consumes ge_history + pcon_geoms_2010 on --region=gb; emits PCON_PATHS_PRE / PCON_ERAS / PCON_HISTORY alongside the existing PCON_PATHS / PCON / ge2024 constants
```

`21b` fetches `Westminster_Parliamentary_Constituencies_Dec_2021_UK_BGC_2022` from the ONS Open Geography Portal. Westminster boundaries did not change between the 2010 Constituencies Order and the July 2024 review, so the December 2021 snapshot describes the same geometry used at all three target elections (2015 / 2017 / 2019); `PCON21CD = PCON15CD = PCON19CD` for all 650 seats. PCON21CD and PCON24CD code spaces are largely disjoint — only 5 unchanged Scottish constituencies overlap (East Renfrewshire, Na h-Eileanan an Iar, Midlothian, North Ayrshire and Arran, Orkney and Shetland) — so 07d uses a `PRE_<PCON21CD>` prefix to keep the two polygon-key sets disjoint, mirroring Senedd's `PRE_<NAWC21CD>` pattern.

`19b` is the project's first use of the HoC Library Cloudflare-bypass path in production. CBP-8647 ships one unified XLSX (one tab per election) keyed by ONS PCON code directly — no name-based join required. The xlsx is gitignored under the existing `data/source/*.xlsx` rule; the long-form csv adds a parallel gitignore entry.

`20b` parses the 2010 / 2015 / 2017 / 2019 sheets, scans row 3 for the per-party Votes columns (Conservative / LibDem / Labour / UKIP / Green / SNP / Plaid / DUP / etc. — note that column positions shift year-on-year: 2010/2015/2017 = Con/LD/Lab/UKIP, 2019 = Con/Lab/LD/Brexit), and selects the winner as the party with the most votes. UKIP / Brexit / DUP / Sinn Féin / SDLP / UUP / Alliance fold to "Other" via `_wiki_parser.normalize_party` — consistent with the GE 2024 extractor's `westminster_party()` wrapper. Four hand-curated Speaker overrides cover Buckingham 2010 + 2015 + 2017 (John Bercow) and Chorley 2019 (Lindsay Hoyle), where HoC otherwise classifies the Speaker's votes under "Other". GB winner totals match the historical record exactly:
- GE 2010: Con 306, Lab 258, LibDem 57, SNP 6, Plaid 3, Green 1, Speaker 1
- GE 2015: Con 330, Lab 232, SNP 56, LibDem 8, Plaid 3, Green 1, Speaker 1, Other 1 (Carswell / UKIP / Clacton)
- GE 2017: Con 317, Lab 262, SNP 35, LibDem 12, Plaid 4, Green 1, Speaker 1
- GE 2019: Con 365, Lab 202, SNP 48, LibDem 11, Plaid 4, Green 1, Speaker 1

07d stamps each `path.pcon` with `data-pcon` and `data-era` (`'pre'` for `PRE_<PCON21CD>`, `'post'` for bare `PCON24CD` — no `'any'` analogue, mirroring Holyrood and Senedd). `paintAtYear`'s `path.pcon` block mirrors the existing `path.holyrood` block, with the era boundary at 2024 (rather than 2026): `era==='pre'` polygons hide at `y >= 2024`, `era==='post'` polygons hide at `y < 2024`. The 632 synthetic PRE_ pcon_js entries carry initial `{w: null, y: null}` so they paint grey until paintAtYear fills them at slider time. The CSS rule `.map-svg.slider-pre-2024 path.pcon` (which previously hid all PCONs at year < 2024) was removed in Phase 1E since paintAtYear's inline `style.display` now manages era-based visibility — same architectural shift CEDs, Holyrood, and Senedd went through.

Phase 1E adds **2015** to the slider year stops (2017 and 2019 already existed via ward / CED contests). The slider's `YEARS` array becomes the union of ward / CED / Holyrood / Senedd / PCON year stops — 11 stops total: `[2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]`. **#80 update:** 2011 is added as a Senedd-only tick, making the array 12 stops total: `[2011, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]`.

Issue #84 extends the Westminster history one stop further back to **2010**. CBP-8647 ships a `2010` sheet alongside the 2015/2017/2019 sheets `20b` already reads, so the only data-side changes were `YEARS = (2010, 2015, 2017, 2019)` in `scripts/20b_extract_ge_history.py` and a fourth `SPEAKER_OVERRIDES` entry for John Bercow (Buckingham 2010). No boundary work was needed: `PCON10CD = PCON15CD = PCON21CD` for all 650 seats per ONS's May-2010 → July-2024 lookup (already noted in `21b`'s header), so the existing 632 `PRE_<PCON21CD>` polygons paint 2010 the same way they paint 2015/2017/2019. The renderer's `YEARS` array is the sorted union of every history layer's `years` list — adding 2010 propagated automatically; no JS changes. GB winner tally at 2010 matches the historical record exactly: Con 306, Lab 258, LibDem 57, SNP 6, Plaid 3, Green 1, Speaker 1 (NI's 18 seats stay grey at render time).

PCON-history click-through opens the HoC Library CBP-8647 briefing page for pre-era seats. Post-era 2024 entries carry an empty URL because `ge2024.json` doesn't ship a per-constituency Wikipedia URL — clicks on 2024 polygons do nothing, matching today's behaviour.

### GLA Mayor overlay (issue #81) → feeds the GB current map historical slider

```
28_fetch_gla_mayor_geom.py     → data/gla_mayor_geom.json    (1 polygon — ONS Region E12000007 = London — sharing the gb viewBox; raw cache at data/source/region_london_dec_2024.geojson)
data/gla_mayor.json            → hand-curated 4 records (2012/2016/2021/2024 mayoral winners with per-year Wikipedia src URLs)
07d_build_current_map_artifact.py → consumes both on --region=gb; emits GLA_MAYOR / GLA_MAYOR_PATH / GLA_MAYOR_HISTORY constants
```

The Greater London mayoral overlay is structurally the smallest layer on the current page: one polygon (the London region, coterminous with the 32 boroughs + City of London), four historical contests, no boundary review across the timeframe. `28` mirrors `21_fetch_pcon_geoms.py` — fetches `Regions_December_2024_Boundaries_EN_BGC` filtered to `RGN24CD='E12000007'` from the ONS Open Geography Portal, simplifies at 100 m, and y-flips into the shared SVG coord space via bounds re-discovered from `ward_geoms.json`.

`data/gla_mayor.json` is hand-curated rather than scraped — four records over a closed timeframe (the next mayoral contest is May 2028), with per-year Wikipedia article URLs as `src` so the tooltip click-through still works. The party labels (Conservative / Labour) route through the existing `_artifact_lib.PARTY_COLOURS_MAP` entries — no palette extensions needed.

07d stamps the single polygon with `class="gla-mayor"` and `data-gla="E12000007"`. There's no `data-era` because the GLA boundary hasn't moved since 2000 — the polygon is always visible at any slider year. `paintAtYear`'s `path.gla-mayor` block walks `GLA_MAYOR_HISTORY['E12000007'].history` for the newest entry with `y <= targetYear` and rewrites the fill + tooltip + dataset URL on every slider tick (same shape as the Holyrood/PCON blocks). This phase adds the slider year stop **2012** to the union — it's PCON-less, CED-less, devolved-less, ward-less, so at year=2012 the GLA polygon is the only layer with a real result (every other layer carries-forward to grey at that position). In the default "recent" view the GLA fill sits at the bottom of the z-order beneath ward/PCON layers, so the dedicated "London Mayor only" view is the way to see it through other layers.

The view picker gains a **"London Mayor only"** button (`data-view="gla-mayor"`) which CSS-isolates the single polygon. GM is byte-identical: 07d gates both data loads on `region == 'gb'` and emits empty `GLA_MAYOR` / `GLA_MAYOR_PATH` arrays for GM (the renderer's existing `if (… || GLA_MAYOR.length)` gate keeps the view picker dormant when the arrays are empty).

### Combined-Authority Mayors overlay (issue #82) → feeds the GB current map historical slider

```
scripts/_ca_mayors.py          → 14-row registry (13 mayoral CAs + abolished North of Tyne) with E47* codes, era stamp, per-year wiki article titles
29_fetch_ca_mayor_geom.py      → data/ca_mayor_geoms.json   (14 polygons — 13 post-era CAs from ONS Combined_Authorities_December_2025 + 1 pre-era polygon (E47000011 North of Tyne) from ONS Combined_Authorities_December_2023; raw caches at data/source/combined_authorities_dec_{2023,2025}.geojson)
data/ca_mayors.json            → hand-curated 29 records covering 13 CAs across 2017–2025 (per-year Wikipedia src URLs)
07d_build_current_map_artifact.py → consumes both on --region=gb; emits CA_MAYORS / CA_MAYOR_PATHS / CA_MAYOR_PATHS_PRE / CA_MAYOR_ERAS / CA_MAYOR_HISTORY constants
```

Sibling to the GLA Mayor pipeline (#81) but scaled from 1 polygon to 14 and with one era split: the **North of Tyne CA** (E47000011, 3-LAD body — Newcastle / North Tyneside / Northumberland) was abolished and reformed in May 2024 as the **North East CA** (E47000014, 7-LAD body — adding Durham, Gateshead, South Tyneside, Sunderland). Because the two ONS codes are disjoint, no synthetic `PRE_` prefix is needed: `regions_pre` carries E47000011 alone (from the Dec 2023 snapshot) and `regions` carries the 13 modern CAs (from the Dec 2025 snapshot, with E47000015 Devon and Torbay + E47000018 Lancashire filtered out — both have CAA/CCA status but no mayoral office on record).

07d stamps each polygon with `class="ca-mayor"`, `data-ca` (the E47 code), and `data-era` (`'pre'` for E47000011, `'post'` for E47000014, `'any'` for the 12 stable CAs). `paintAtYear`'s `path.ca-mayor` block toggles inline `style.display` per the existing CED/Holyrood/Senedd/PCON era convention — `pre` hides at `y >= 2024`, `post` hides at `y < 2024`, `any` is always visible — then walks `CA_MAYOR_HISTORY[code].history` for the newest entry with `y <= targetYear` and rewrites the fill + tooltip + click-through URL.

`data/ca_mayors.json` is hand-curated (no fetcher/extractor pair) for the same reason as `data/gla_mayor.json`: the dataset is small (29 records), closed (the next CA mayoral contests are May 2026 and beyond — Greater Manchester / South Yorkshire / Liverpool City Region / Tees Valley / West Midlands / West Yorkshire each held their last contest in 2024, so the next is 2028 except for any newly-established CAs), and each row is primary-source verifiable against the linked Wikipedia article. Party labels (Labour / Conservative / Reform) route through the existing `_artifact_lib.PARTY_COLOURS_MAP` entries — no palette extensions needed.

**Note on the issue table's year accuracy:** issue #82's table listed Cambridgeshire & Peterborough and West of England with election years "2017, 2021, 2024", but Wikipedia confirms both CAs ran their third contest in **May 2025** (not 2024). The 2025 contests are captured in the data file with the canonical `2025_<CA>_mayoral_election` URLs.

The view picker gains a **"CA mayors only"** button (`data-view="ca-mayor"`) which CSS-isolates the 14 CA polygons. GM is byte-identical: 07d gates both data loads on `region == 'gb'` and emits empty `CA_MAYORS` / `CA_MAYOR_PATHS` arrays for GM (the renderer's existing `if (… || CA_MAYORS.length)` gate keeps the view-picker dormant when the arrays are empty). The slider gains no new year stops — every CA mayoral year (2017 / 2018 / 2019 / 2021 / 2022 / 2024 / 2025) is already in the union via ward / CED / Holyrood / Senedd / PCON / GLA-Mayor contests.

### Surrey unitary overlay pipeline (issue #4 §4) → feeds the GB current map AND the GB map page

```
22_fetch_surrey_results.py     → data/source/wiki_surrey_*_2026.json  (idempotent — skips cached files)
23_extract_surrey.py           → data/surrey_2026.json                (81 records: lad_code, ward_code, ward_name, winner, seats_won, votes, candidate)
24_fetch_surrey_geoms.py       → data/surrey_geoms.json               (81 SVG paths sharing the gb viewBox; raw cache at data/source/lgbce/surrey_mapping_files.zip)
07c_build_map_artifact.py      → emits SURREY / SURREY_PATHS on --region=gb (painted on the After view only — no prior election under this geography)
07d_build_current_map_artifact.py → consumes both outputs and emits SURREY / SURREY_PATHS arrays on --region=gb
```

East Surrey and West Surrey were elected on 7 May 2026 but don't take administrative effect until 1 April 2027 — ONS has not assigned LAD25 codes or shipped a WD25 lookup. The registry at `scripts/_surrey_unitaries.py` uses synthetic LAD codes `XSE` / `XSW`, mirroring `_senedd_constituencies.py`'s pattern, plus a per-unitary list of predecessor district GSS codes used at geometry-split time. `23` reuses `_wiki_parser.normalize_party` and walks paired `{{Election box begin|title=…}}` / `{{Election box end}}` blocks; the "winning candidate" template marker drives seat allocation. `24` fetches the LGBCE Surrey May 2024 final-recommendation shapefile (`Surrey_F_EDs_polygons.shp`, 82 features → 81 wards after dissolving the multipart Lightwater and re-splitting the "East Molesey & The Dittons" division by centroid latitude — East Surrey "modified" it into two named wards), splits each polygon East/West by the LGBCE shapefile's `District` column, simplifies at 50 m, and y-flips into the same SVG coord space as the WD24 wards using the same bounds-from-`ward_geoms.json` recipe `16` uses for Senedd. `07c` and `07d` both gate on `region == 'gb'`; GM is byte-identical.

Wikipedia ward results are appended incrementally post-election. Wards without a `{{Election box winning candidate}}` template carry `winner='Pending'` and paint with the Pending palette colour; re-running `22` → `23` picks up newly-declared results idempotently. Today's baseline: **36/36 XSE wards decided** (72/72 seats); West Surrey is **23/45 wards decided** (46/90 seats) with the 22 pending wards listed in `23`'s stderr summary.

### EU Referendum 2016 LAD-level overlay pipeline (issue #85) → feeds the GB current map only

```
25_fetch_eu_ref.py            → data/source/ec_eu_referendum_2016.csv   (Electoral Commission per-counting-area CSV; idempotent — skips cached file)
26_extract_eu_ref.py          → data/eu_ref_2016.json                   (380 GB LADs: leave_votes, remain_votes, pct, plurality winner)
27_fetch_lad_2016_geoms.py    → data/lad_geoms_2016.json                (380 LAD16CD polygons sharing the gb viewBox; raw cache at data/source/lad_dec_2016_gb_bgc.geojson)
07d_build_current_map_artifact.py → consumes both on --region=gb; emits EU_REF / EU_REF_PATHS arrays + .view-eu_ref_2016 toggle + Leave/Remain palette entries
```

`25` fetches the Electoral Commission CSV (the canonical primary source — tier 2 in the accuracy hierarchy) from a stable CDN-cached URL on `electoralcommission.org.uk`. The CSV itself is not Cloudflare-gated (the EC's HTML pages are, but the asset bypasses the challenge), so a plain `urllib` GET with a real-browser User-Agent works; if that ever changes, swap in `scripts/_official_parsers/_cloudflare.py::cloudflare_session()` the same way `19b` does.

`26` parses 382 counting areas, filters NI (1 row: `N92000002`) and Gibraltar (1 row: `GI`) because the `gb` viewBox excludes both, and emits 380 LAD-keyed records in the `ge_history.json` schema family (`{years, lads: {LAD16CD: {name, history: [{y, w, src, url, votes, pct}]}}}`). The `pct` field is pre-computed at extract time so 07d's tooltip can splice "Leave 53.4% / Remain 46.6%" without re-floating the totals in JS on every hover. `w` is the plurality winner as the literal string `"Leave"` or `"Remain"`; the same PARTY_COLOURS lookup that paints party winners paints the referendum (new `Leave` / `Remain` entries land in `_artifact_lib.PARTY_COLOURS_MAP`).

EU referendum counting areas in 2016 used the **2016-era** LADs — Dorset/BCP, Buckinghamshire, N/W Northants, Cumberland/Westmorland & Furness, Somerset, and North Yorkshire all post-date the referendum, so painting on today's `boroughs` (dissolved from WD24 wards in `09`) would smear historical results across reorganised authorities. `27` fetches the ONS `LAD_Dec_2016_GB_BGC_2022` layer fresh and y-flips it into the same `gb` SVG coord space as Senedd/PCON/Surrey via the bounds-from-`ward_geoms.json` recipe `16` / `21` / `24` already use. The `_GB_` infix on the ONS layer excludes NI server-side, so the layer ships 380 features matching `26`'s output 1:1.

`scripts/_referendums.py` is a shared registry covering all three UK-wide referendums (#84 GE 2010, #85 EU ref 2016, #86 Indyref 2014) and exposes a `LAD_2016_TO_2024` predecessor→successor mapping for 37 reorganised English districts. The mapping is **not load-bearing for #85** (because we paint on 2016-vintage polygons) — it's forward-looking infrastructure for any future view that paints historical referendum results on current LAD geometry, plus a foundation for #84 / #86.

The renderer in 07d stamps each `<path class="referendum">` with `data-lad` (the LAD16CD) and `data-url` (the EC results page) so click-through opens the source. There's no era logic — EU ref is single-vintage and visibility is purely CSS-gated by the dedicated `view=eu_ref_2016` button in the top bar. When that view is active, every other thematic layer (`path.ward / path.ced / path.holyrood / path.senedd / path.pcon / path.surrey`) is hidden by CSS; in every other view the referendum layer itself is hidden. So readers only see the EU ref polygons when they opt in. The slider does NOT interact with this layer (no entry in `paintAtYear`), so moving the slider while EU Ref view is active doesn't change what paints. GM is byte-identical to the pre-EU-ref state inside the BEGIN/END markers other than the empty `EU_REF` / `EU_REF_PATHS` constants emitted for shared-renderer consistency — same convention Senedd/PCON/Surrey follow.

### Official-source pipeline (issue #9) → feeds 04c at higher priority than Wikipedia

```
12_fetch_official_results.py   → data/source/official_<slug>_<year>.{html|json|pdf}   (idempotent — skips cached files)
13_extract_official.py         → data/source/{county,ward}_official_<year>.csv         (appends rows from registered parsers; preserves hand-curated rows for councils without a parser)
04c_build_current_winners.py   → as above, with official rows outranking both Wikipedia and all_wards.json per-record (county-side via county_official_<year>.csv, ward-side via ward_official_<year>.csv)
```

Each council in `councils.yaml` may declare `official_url` + `official_parser` + `official_year`. `12` fetches the URL (default GET; parser modules can override `fetch()` for Power BI etc.) into the cache. `13` dispatches on `official_parser` to `scripts/_official_parsers/<key>.py` and appends rows. CSV schemas: `lad_code,county,division,party,candidate,votes,source` for E10 counties; `lad_code,council,ward,party,candidate,votes,source` for everything else.

Parsers landed for Phase 2 of issue #9 (county-level, E10 prefix):
- `arcgis_dashboard` — Esri Election Results FeatureServer (East Sussex)
- `moderngov_per_division` — moderngov.co.uk per-division pages (West Sussex; reused for Greater Manchester wards in Phase 4-GM and for 27 non-GM 2026 districts/unitaries/metros/London boroughs in Phase 4-MG)
- `cmis_per_division` — DotNetNuke / OpenElection.net RDFa pages (Essex)
- `powerbi_dashboard` — Power BI publish-to-web DAX scraper (Suffolk)
- `hampshire_cloudflare` — single all-divisions HTML table behind Cloudflare; uses `scripts/_official_parsers/_cloudflare.py` (curl_cffi Chrome TLS impersonation) to bypass the 403 (Hampshire)
- Phase 1 hand-curated CSV pattern still in use for Norfolk (no parser yet)

Parsers landed for Phase 4 priority subset of issue #9 (Greater Manchester wards, E08 prefix):
- `moderngov_per_division` — reused for Rochdale, Stockport, Tameside (each on their own `democracy.<council>.gov.uk` or `<council>.moderngov.co.uk` host). The candidate-name regex was widened to also accept names wrapped in a sitting-councillor `<a>` tag, in addition to West Sussex's bare-text form.
- `bolton` — bespoke single-page article with `<h4>WardName</h4>` blocks; the elected row's votes cell ends in "(elected)".
- `manchester` — bespoke directory page with `<h3>WardName</h3>` blocks and a `<ul>` of candidates as `<li>NAME, Firstname (Party): N votes - elected</li>` rows wrapped in `<strong>` for the winner.
- `oldham` — bespoke results page with `<h2>WardName</h2>` blocks; the elected row's votes cell carries `<strong>VOTES Elected</strong>`.
- `salford` — bespoke results page with `<h3>WardName</h3>` blocks; the elected row opens with a stray `<strong> </strong>` marker before the candidate `<p>` (which losing rows lack); a tag-stripping cleanup also handles winners whose names span two `<strong>` tags joined by `<br>` (Eccles' Tetteh, Nathaniel Djangmah). For double-vacancy wards (Cadishead and Lower Irlam in 2026) we yield only the first-listed elected row, mirroring `moderngov_per_division`'s multi-seat convention.
- `trafford` — bespoke single-page article with `<h2 id="...">WardName</h2>` blocks and a 4-column table (Surname / Forename / Description / Votes); each cell of the elected row is wrapped in `<strong>` with a `*` after the votes. The cell-content cleaner handles party names split across two `<strong>` tags joined by `<br>` ("Labour and Co"<br>"operative Party").
- `wigan` — dedicated ASP.NET MVC subdomain (`electionresults.wigan.gov.uk`) with a `/LocalElections/Home/Index/{eid}` ward index and `/LocalElections/Ward/Index/{wid}` per-ward pages; custom `fetch()` walks the index and bundles every ward into a single JSON cache, mirroring `moderngov_per_division`.
- Bury (E08000002) is **deferred** from this batch — its results live behind a Contensis SPA on `bury.gov.uk` whose Delivery API is auth-gated and whose server-rendered HTML carries no per-ward votes/winners. The 16 declared 2026 winners come from `all_wards.json` (Wikipedia) via Pass 1a of `04c`; Bury Moorside stays the structural grey on the GM map (re-poll within 35 days of 7 May 2026 following a candidate's death). See the inline comment above the Bury row in `councils.yaml`.

Parsers landed for Phase 4 / non-GM ModernGov subset of issue #9 (#36):
- `moderngov_per_division` — reused for 27 non-GM 2026 councils (no new parser needed). Coverage by lad_code prefix: 5 × E06 unitaries (Thurrock, Wokingham, Milton Keynes, Portsmouth, Isle of Wight), 12 × E07 districts (Cambridge, Hastings, Brentwood, Epping Forest, Rochford, Cheltenham, Fareham, Gosport, Hart, Tunbridge Wells, Lincoln, Crawley), 2 × E08 metros (Bradford, Kirklees), 8 × E09 London boroughs (Bexley, Brent, Harrow, Lewisham, Merton, Sutton, Tower Hamlets, Wandsworth). Each council's 2026 EID was discovered by `scripts/_phase4_survey_moderngov.py` and confirmed by hand-walking the council's `mgElectionResults.aspx?bcr=1` listing — important for E07 districts that also host their *county's* 2026 EID on the same instance, where the probe's first match is usually the county election, not the district's own.
- `moderngov_per_division_incapsula` — sibling parser re-exporting `parse()` from `moderngov_per_division` but overriding `fetch()` to go through `_cloudflare.cloudflare_session()` with rotating Chrome impersonations and Incapsula-bounce detection (mirrors `scripts/22_fetch_surrey_results.py`'s recipe). **No #36 hits use it yet** — the Phase 4-MG probe surfaced zero non-GM councils behind Incapsula — but it's available for any future ModernGov host fronted by Imperva. Surrey CC's `mycouncil.surreycc.gov.uk` is the canonical example of the pattern this parser addresses.
- `scripts/_phase4_survey_moderngov.py` — one-off discovery helper (not invoked by 10/11/12/13/04c/07d). Probes every non-GM 2026 council in `councils.yaml` for `<slug>.moderngov.co.uk` and `democracy.<slug>.gov.uk` host patterns, classifies plain/incapsula/none, and extracts the 2026 EID where the listing page exposes it. Output is stderr only — review the table before editing `councils.yaml`.

The `_cloudflare.py` helper (private module — leading underscore, never declared as `official_parser`) exposes `cloudflare_session()` and `fetch_cloudflare()` so any future Phase 4/5 council fronted by Cloudflare can opt in by importing it; `curl_cffi` is lazy-imported to keep contributors who don't run a CF-bypass parser from needing the wheel installed.

For counties where the 2025/2026 LGBCE review redrew divisions, `scripts/09c_overlay_lgbce_ceds.py` replaces the pre-review CED25 polygons in `data/ward_geoms.json` with post-review polygons sourced from each county's LGBCE final-recommendation shapefile (Norfolk, Essex, Suffolk today). The shapefile zips cache under `data/source/lgbce/` and are fetched idempotently. Spelling differences between LGBCE and the council's published CSV are reconciled by the `NAME_FIXES` map at the top of `09c`.

As a fallback for any future county where we have results but no post-review polygons, `04c` also consults `data/source/ced_name_overrides.csv` (schema: `cty_code,ons_name,csv_division,note`) — geometry-side → result-side, mirroring `ward_name_overrides.csv`. Currently empty for Norfolk/Essex/Suffolk because the LGBCE overlay handles them; reserved for future counties.

Common cases:

- **Touched `scripts/0[1-6]_*.py` or input XLSX** → run that Winners script and every later one, ending with 07. If the change touches `all_wards.json`, also re-run `04b → 05b/05c → 06b → 07b` for Changes, `07c` for Map, and `04c → 07d` for Current (all three read downstream of `04`).
- **Touched `scripts/07_build_artifact.py`** → run 07 only.
- **Touched `scripts/0[145-7]b_*.py` or `05c_*.py`** → run from that script onwards through 07b. Also re-run 07c if `all_wards_with_prior.json` changed.
- **Touched `scripts/07c_build_map_artifact.py`** → run `07c --region=gm` and `07c --region=gb`.
- **Touched `scripts/10_*.py` / `11_*.py` / `04c_*.py` / `04d_*.py` / `_wiki_history.py`** → run from that script onwards through `07d --region=gm` and `07d --region=gb`. If only `04d` or its inputs changed, the GM artifact is byte-identical (WARD_HISTORY/YEARS only ship on `--region=gb`).
- **Touched `scripts/04e_build_ced_history.py` / `scripts/09e_overlay_pre_review_ceds.py` / `_wiki_parser.py::parse_county_article*`** → run from that script onwards. For `04e` alone: `04e` → `07d --region=gm` (byte-identical: CED_HISTORY only ships on `--region=gb`) → `07d --region=gb`. For `09e` (which writes `ceds_pre_review` into `ward_geoms.json`): `09e --force` → `04e` → `07d` (both regions). For `_wiki_parser` changes: also re-run `11` → `04c` (CED-side outputs may shift) → `04e` → `07d` (both regions).
- **Added historical `wiki_current_articles` entries to `data/source/councils.yaml`** → run `10` (fetches new articles idempotently; the misses report any 404s — remove or override those rows in YAML and re-run), then `11` → `04c` (should be byte-identical: 04c is first-write-wins on newest entries) → `04d` → `07d --region=gb`. GM byte-identical.
- **Touched `scripts/12_*.py` / `13_*.py` or a module in `scripts/_official_parsers/`** → run `12` → `13` → `04c` → `07d --region=gm` → `07d --region=gb`. The fetcher and extractor are no-ops when no councils have `official_url` set, so a structural change without a registered council should leave `04c` output byte-identical.
- **Added an `official_url` / `official_parser` / `official_year` triple to a council in `data/source/councils.yaml`** → run `12` → `13` → `04c` → `07d` (both regions).
- **Added or edited a row in `data/source/ced_name_overrides.csv`** → run `04c` → `07d` (both regions). The override boosts `matched` in 04c's summary line; check the per-county counts to confirm the new row landed where you expected.
- **Added a county to `scripts/09c_overlay_lgbce_ceds.py` (new LGBCE shapefile)** → run `09c --force` → `04c` → `07d` (both regions). Confirm the per-county count is 100 % (or notes the gap if a specific division has no result).
- **Touched `scripts/07d_build_current_map_artifact.py`** → run `07d --region=gm` and `07d --region=gb`.
- **Added rows or `wiki_current_articles` entries in `data/source/councils.yaml`** → run `10` → `11` → `04c` → `07d` (both regions). New rows with `wiki_2026` set also need `00b` and the Winners cascade.
- **Touched `scripts/14` / `15` / `16` or `scripts/_senedd_constituencies.py`** → run from that script onwards through `07d --region=gm` and `07d --region=gb`. The GM page is gated on `region == 'gb'` and will produce a byte-identical diff.
- **Touched `scripts/19` / `20` / `21` or `scripts/_ge2024_constituencies.py`** → run from that script onwards through `07d --region=gm` and `07d --region=gb`. GM is byte-identical (PCON gated on `region == 'gb'`, like Senedd).
- **Touched `scripts/19b_fetch_ge_history.py` / `scripts/20b_extract_ge_history.py` / `scripts/21b_fetch_pcon_2010_geoms.py`** → run from that script onwards through `07d --region=gm` (byte-identical: PCON_HISTORY / PCON_PATHS_PRE only ship on `--region=gb`) and `07d --region=gb`. For `19b` (HoC Library re-fetch): `19b --force` only if you suspect the upstream file changed; HoC publishes corrigenda infrequently. For `20b` alone (parser or Speaker-override change): `20b` → `07d` (both regions). For `21b` (boundary geometry): `21b --force` → `07d` (both regions).
- **Touched `scripts/22` / `23` / `24` or `scripts/_surrey_unitaries.py`** → run from that script onwards through `07c --region=gm`, `07c --region=gb`, `07d --region=gm`, `07d --region=gb`. GM is byte-identical for both pages (Surrey overlay gated on `region == 'gb'`). The renderers consume both `data/surrey_2026.json` and `data/surrey_geoms.json` directly, so a script change without re-running 23/24 ships stale data.
- **Touched `scripts/25_fetch_eu_ref.py` / `scripts/26_extract_eu_ref.py` / `scripts/27_fetch_lad_2016_geoms.py` / `scripts/_referendums.py`** → run from that script onwards through `07d --region=gm` and `07d --region=gb`. The EU ref overlay is GB-only (gated on `region == 'gb'`); GM ships empty `EU_REF` / `EU_REF_PATHS` constants for shared-renderer consistency. For `25` alone (re-fetch of the EC CSV): `25 --force` only if you suspect the upstream file changed (EC publishes corrigenda very infrequently — the URL has been stable since 2019-07-26). For `27` alone (boundary geometry): `27 --force` → `07d` (both regions). For `26` alone (parser change): `26` → `07d` (both regions).
- **Touched `scripts/28_fetch_gla_mayor_geom.py` or `data/gla_mayor.json`** → run `28 --force` (only if geometry needs refetching; `28` is idempotent and exits early when `data/gla_mayor_geom.json` exists) then `07d --region=gm` (byte-identical: GLA_MAYOR / GLA_MAYOR_HISTORY only ship on `--region=gb`) and `07d --region=gb`. Editing `data/gla_mayor.json` alone (the 4 hand-curated mayoral records) skips 28 entirely and just needs `07d` re-run for both regions.
- **Touched `scripts/29_fetch_ca_mayor_geom.py` / `scripts/_ca_mayors.py` / `data/ca_mayors.json`** → for geometry refetch: `29 --force` → `07d --region=gm` (byte-identical: CA_MAYORS / CA_MAYOR_HISTORY only ship on `--region=gb`) → `07d --region=gb`. For registry edits alone (`scripts/_ca_mayors.py` — only the geometry fetcher imports it, plus the 07d coverage report): `29` won't re-emit polygons unless the keep-codes set changed; safest is `29 --force` + 07d rebuild. For `data/ca_mayors.json` edits alone (the 29 hand-curated records): skip 29 entirely and just rerun `07d` for both regions.
- **Touched `scripts/04f_build_holyrood_history.py` / `scripts/09f_overlay_pre_review_holyrood.py` / `scripts/17b` / `scripts/18b` / `scripts/_holyrood_constituencies.py`** → run from that script onwards. For `04f` alone: `04f` → `07d --region=gm` (byte-identical: HOLYROOD_HISTORY only ships on `--region=gb`) → `07d --region=gb`. For `09f` (which writes `spcs_pre_review` into `ward_geoms.json`): `09f --force` → `04f` → `07d` (both regions). For `17b` (registry edits or new wiki_title overrides): `17b --force` for the affected SPC22CD only (delete that cached file and re-run), then `18b` → `04f` → `07d` (both regions). For `18b` (parser changes): `18b` → `04f` → `07d` (both regions).
- **Added or edited a row in `data/source/holyrood_official_<year>.csv`** → run `04f` → `07d` (both regions). Each row overrides the wiki extraction at that (constituency, year) — the per-region counters in 04f's stderr summary show whether the row landed where you expected.
- **Touched `scripts/04g_build_senedd_history.py` / `scripts/14b` / `scripts/15b` / `scripts/16b_fetch_senedd_2007_geoms.py` / `scripts/_senedd_constituencies_2007.py`** → run from that script onwards. For `04g` alone: `04g` → `07d --region=gm` (byte-identical: SENEDD_HISTORY / SENEDD_REGION_HISTORY only ship on `--region=gb`) → `07d --region=gb`. For `16b` (which writes the standalone `data/senedd_geoms_2007.json`): `16b --force` → `04g` → `07d` (both regions). For `14b` (registry edits or new wiki_title overrides): delete the affected cached file under `data/source/wiki_senedd_constituency_*.json` or `data/source/wiki_senedd_region_*.json`, re-run `14b`, then `15b` → `04g` → `07d` (both regions). For `15b` (parser changes): `15b` → `04g` → `07d` (both regions).
- **Added or edited a row in `data/source/senedd_official_<year>.csv`** → run `04g` → `07d` (both regions). Each row overrides the wiki extraction at that (constituency, year) for years < 2026. The CSV is hand-curation reserved for Wikipedia gaps — currently empty since 15b achieves 40/40 × 3 years coverage off the wiki cache alone (2011, 2016, 2021 each 40/40 after #80).
- **Wikipedia updated West Surrey ward results** → run `22` → `23` → `07c --region=gb` → `07d --region=gb`. `23`'s stderr summary names the still-pending wards; if it shrinks from today's 22, the new winners drop into the map automatically.
- **Touched `scripts/09_fetch_ward_boundaries.py` or boundary set** → run `09 --force` then `07c --region=gm`, `07c --region=gb`, `07d --region=gm`, `07d --region=gb`. The Senedd y-flip in `16` reads bounds from `ward_geoms.json`, so re-run `16 --force` too if 09's bounds shift.
- **Touched only copy/CSS in any of the four HTMLs** → no rebuild needed, but verify the BEGIN/END block didn't drift.

After any rebuild, `git diff docs/*.html` should only show changes inside the BEGIN/END markers (plus whatever you intentionally edited outside them). If unrelated chunks moved, something's wrong — investigate before committing.

## Before saying a task is done

1. If the task changed Winners data/scripts/renderer: confirm `07_build_artifact.py` ran cleanly and printed its summary line.
2. If the task changed Changes data/scripts/renderer: confirm `07b_build_changes_artifact.py` ran cleanly and printed its summary line.
3. If the task changed Map data/scripts/renderer: confirm `07c_build_map_artifact.py` ran cleanly for both `--region=gm` (must be 215/215 wards) and `--region=gb` (currently `2426/2434 results-side wards joined to a polygon`, with `8 ward(s) dropped from the map: override polygon already claimed by a direct-match ward`). The 8-drop residual is structural and tracked in issue #4 §3: Calderdale (+1), Swindon (+5), and Milton Keynes (+2) each added more 2026 wards than they had pre-2024 polygons, so the surplus new wards have no unclaimed WD24 proxy to claim (the exact list is `Calderdale::Wainhouse`, `Swindon::{Highworth, Penhill & Pinehurst, Rodbourne Ferndale and Western, St Andrews West and Tadpole, Upper Stratton}`, `Milton Keynes::{Great Linford, Ouzel Valley}`). They stay in the analysis tables; only the GB map can't paint them. Any change to the matched / dropped counts beyond this baseline means the GSS join lost wards and needs investigation.
4. If the task changed Current data/scripts/renderer: confirm `07d_build_current_map_artifact.py` ran cleanly for both `--region=gm` (must be 215/215 wards) and `--region=gb` (today's baseline is 7,934 GB ward-based wards with **7,931 winner-coloured + 3 grey** — the 3 grey are Isle of Wight 2026 boundary-review drift (Freshwater South, Nettlestone & Seaview, Newport Central — WD24 polygons that no longer exist as wards under IOW's 2026 election); the prior 9-grey STV residual closed in PR #60 via the unopposed-template fallback in `parse_stv_article` plus a hand-curated Moray Buckie row, and the 2025-all-out boundary-review unitaries closed via N:1 `current_ward_overrides.csv` rows. The GB run should also log `ceds in gb: 1,613 (with winner: 1,314; grey: 299; incl. 298 pre-review polygons hidden at year >= 2026)` (1,314 = 84 LGBCE Norfolk + 78 LGBCE Essex + 69 LGBCE Suffolk + 1,083 bare CED25CDs across 17 unchanged counties − the still-grey Chelmsford Springfield LGBCE entry; 299 grey = 298 PRE_ polygons rendered hidden at the slider's default year + 1 Chelmsford Springfield content gap), `holyrood spcs in gb: 146 (with winner: 73; grey: 73; incl. 73 pre-review polygons hidden at year >= 2026)` (Phase 1C / #74: 73 SPC26 polygons paint 2026 + 73 PRE_<SPC22CD> polygons hide at year >= 2026 and paint 2016+2021 at year < 2026), `senedd in gb: 56 (with winner: 16; grey: 40; incl. 40 pre-review polygons hidden at year >= 2026)` (Phase 1D / #72 + #80: 16 S0x polygons paint 2026 + 40 PRE_<NAWC21CD> polygons hide at year >= 2026 and paint 2011/2016/2021 at year < 2026), `pcon in gb: 1,264 (with winner: 632; grey: 632; incl. 632 pre-review polygons hidden at year >= 2024)` (Phase 1E / #71 + #84: 632 PCON24CD polygons paint 2024 + 632 PRE_<PCON21CD> polygons hide at year >= 2024 and paint 2010/2015/2017/2019 at year < 2024), `surrey in gb: 81 (decided: 81; pending: 0)`, `eu_ref_2016 in gb: 380 (decided: 380; grey: 0)` (issue #85: 326 English + 22 Welsh + 32 Scottish 2016-era LADs painted Leave/Remain; NI + Gibraltar filtered out; visible only when the dedicated "EU Ref 2016" view is active), `gla mayor in gb: 1 polygon, 4 years` (issue #81: one polygon, four mayoral contests 2012/2016/2021/2024), `ca mayors in gb: 14 polygons, 7 years (13 post-era + 1 pre-era hidden at year >= 2024)` (issue #82: 13 mayoral CAs from the Dec 2025 ONS snapshot + 1 pre-era polygon (North of Tyne, abolished May 2024) from the Dec 2023 snapshot; 29 contests total across 2017–2025), `ward history: 7,934 wards across 9 year stops, ~19,000 ward-years` (issue #70 phase 1A + #73 phase 1B extended SLIDER_YEARS to start at 2017), `ced history: 1,613 CED polygons across 4 year stops, ~3,800 CED-years` (issue #69 phase 1B / #73), `holyrood history: 146 SPC polygons across 3 year stops, ~219 SPC-years` (issue #69 phase 1C / #74), `senedd history: 56 constituency polygons + 5 regions across 4 year stops (136 constituency-years, 15 region-years)` (issue #69 phase 1D / #72 + #80 2011 extension), `ge history: 632 pre-era + 632 post-era PCON polygons across 5 year stops (2,528 PCON-years from HoC + 632 from ge2024.json)` (issue #69 phase 1E / #71, extended back to 2010 in #84), and `15`'s summary should read `16/16 constituencies, 96/96 seats accounted for`. The GB slider's `YEARS` array is the union of ward/CED/Holyrood/Senedd/PCON/GLA-Mayor/CA-Mayor year stops — 14 stops total: `[2010, 2011, 2012, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]`. CA-Mayor (#82) adds zero new stops; every CA mayoral year (2017/2018/2019/2021/2022/2024/2025) was already in the union via ward/CED/PCON/GLA-Mayor contests. 2010 is PCON-only (Phase 1E / #84 extension); 2011 is Senedd-only (no other contests on record); 2012 is GLA-Mayor-only (Boris Johnson re-election; every other layer carries-forward to grey at that position); 2015 is PCON-only (no ward / CED / devolved contests; wards carry-forward); 2016 is Holyrood + Senedd + GLA Mayor (Sadiq Khan's first win; wards carry-forward).
5. `git status` / `git diff docs/*.html` — make sure the spliced output is committed alongside the script changes (the deployed artifacts are the HTMLs, not the scripts; an un-rebuilt commit ships stale data).
6. If you only changed copy/CSS outside the markers, no rebuild is required — say so explicitly rather than running 07/07b/07c/07d "just in case" (a no-op diff is fine, but skip the noise).

## Deployment

GitHub Pages serves the entire `docs/` directory from `main` directly — `docs/index.html`, `docs/changes.html`, `docs/map.html`, `docs/current.html`, the `docs/uk/` mirrors, and `docs/shared.css` all deploy as-is, no CI build step. The committed HTML *is* the deployment. This makes the "did you re-run 07/07b/07c/07d?" check load-bearing: a commit with updated data scripts but stale HTML will deploy stale numbers.

## PR / issue conventions

When a PR fully resolves an issue, put a GitHub closing keyword (`Closes #N`, `Fixes #N`, `Resolves #N`) on its own line in the PR **body**. Title-only references like `feat(foo): bar (#30)` do not auto-close — they only show up as a backlink. Verify with `gh pr view <PR> --json closingIssuesReferences`; an empty array means the issue will stay open after merge.

When a PR closes only **part** of a larger issue (e.g. one bucket of a meta-issue, one phase of a multi-phase plan), do **not** use a closing keyword. Instead, write `Partially addresses #N — closes the X bucket` in the body so the link is recorded without auto-closing the parent issue. Examples in the wild: PR #43 closed only the boundary-review unitary bucket of #7; PR #40 was Phase 2 of #9, not the whole pipeline.

Sub-issues that exist purely as trackers (e.g. `#9 INFRA`, `#9 GM`) follow the same rule — a PR that implements the full sub-issue scope uses `Closes #N`; a PR that ships one parser inside a multi-parser sub-issue does not.

## Note on prior-winner data source

The Changes pipeline scrapes per-ward 2022/2021 winners from per-borough Wikipedia articles via `00_fetch_prior_winners.py` (cached in `data/source/wiki_*.json`). The original plan was to use the House of Commons Library annual XLSX handbooks, but `commonslibrary.parliament.uk` is behind a Cloudflare managed challenge that blocks programmatic clients. Wikipedia's per-ward `{{Election box winning candidate}}` templates are at least as easy to parse, and re-runs hit the cached files rather than re-fetching.
