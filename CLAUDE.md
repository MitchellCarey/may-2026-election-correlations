# Repo notes for Claude

## `docs/index.html` is partially generated

The page is the deployable artifact (GitHub Pages serves it directly), but it is **not** purely hand-written. `scripts/07_build_artifact.py` splices generated JavaScript into it between two markers:

```
// ===== BEGIN GENERATED — see scripts/07_build_artifact.py =====
…
// ===== END GENERATED =====
```

Everything **outside** those markers (the `<head>`, CSS, copy, section markup, footer) is hand-authored and preserved across builds. Everything **inside** is overwritten on every run of `07_build_artifact.py`.

### Where to make a change

| You want to change… | Edit here |
|---|---|
| Copy, headlines, captions, byline, methodology prose | `docs/index.html` (outside markers) |
| Page styling / fonts / layout | `docs/index.html` `<style>` block |
| The shape of the rendered data (RAW fields, label dictionaries, sort order, party colours) | `scripts/07_build_artifact.py`, then re-run it |
| Data values themselves (winners, census numbers, correlations, means) | upstream scripts 01–06, then re-run 07 |

**Never hand-edit anything between the BEGIN/END markers.** Those edits will be wiped the next time anyone runs the build, and the diff is easy to miss in review.

## Keeping the artifact current

The pipeline is linear; only re-run from the earliest step that's actually stale.

```
01_build_results.py          → data/all_gm_results.json
02_match_gss.py              → data/all_gm_gss_mapping.json
03_extract_census.py         → data/all_gm_census.json     (needs data/source/*.xlsx)
04_consolidate.py            → data/gm_all_wards.json
05_correlate.py              → data/gm_correlations.json
06_prep_artifact_data.py     → data/v12_ward_data.json
07_build_artifact.py         → splices into docs/index.html
```

Common cases:

- **Touched any `scripts/0[1-6]_*.py` or input XLSX** → run that script and every later one, ending with 07.
- **Touched `scripts/07_build_artifact.py`** → run 07.
- **Touched data JSON in `data/` directly** (rare; usually a manual override) → run 07.
- **Touched only copy/CSS in `docs/index.html`** → no rebuild needed, but verify the BEGIN/END block didn't drift.

After any rebuild, `git diff docs/index.html` should only show changes inside the BEGIN/END block (plus whatever you intentionally edited outside it). If unrelated chunks moved, something's wrong — investigate before committing.

## Before saying a task is done

1. If the task changed data, scripts, or the renderer: confirm `07_build_artifact.py` ran cleanly and printed its summary line.
2. `git status` / `git diff docs/index.html` — make sure the spliced output is committed alongside the script changes (the deployed artifact is the HTML, not the scripts; an un-rebuilt commit ships stale data).
3. If you only changed copy/CSS outside the markers, no rebuild is required — say so explicitly rather than running 07 "just in case" (it'll produce a no-op diff, which is fine, but skip the noise).

## Deployment

GitHub Pages serves `docs/index.html` from `main` directly — there is no build step in CI. The committed HTML *is* the deployment. This makes the "did you re-run 07?" check load-bearing: a commit with updated data scripts but a stale HTML will deploy stale numbers.
