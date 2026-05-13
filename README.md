# Greater Manchester 2026 — Ward-Level Structural Analysis

A data-journalism artifact analysing the structural correlates of party performance
across all 214 wards in the 10 Greater Manchester boroughs at the 7 May 2026
local elections.

## Headline finding

**Reform vs % apprenticeship: r = +0.64 across 213 declared GM wards.**
The single strongest correlation in the matrix at this scale, weakened only
slightly from the 48-ward Manchester+Salford sample (+0.75). Reform's mean
ward has 6.8% apprenticeship-trained residents vs 3.2% in Green wards.

The Reform-vs-Green split is the clearest demographic axis in GM politics:

| Variable             | Green (n=30) | Reform (n=104) |
|----------------------|-------------:|---------------:|
| Density (per km²)    |        6,229 |          2,664 |
| Median age           |         30.7 |           40.1 |
| % aged 18-29         |        29.3% |          13.7% |
| % aged 65+           |         8.7% |          18.1% |
| % apprenticeship     |         3.2% |           6.8% |
| % degree (L4+)       |        40.6% |          26.3% |
| % UK-born            |        69.1% |          90.2% |
| % working from home  |        34.1% |          23.8% |
| % private renting    |        36.9% |          16.8% |

LibDem (n=19) and Conservative (n=11) wards both have high SOC 1-3 / WFH /
degree shares; they split on density (Conservatives win the lower-density
rural-fringe end). Labour (n=34) shows the weakest structural signal of any
major party — the largest correlation is just +0.23.

## What's in the repo

Live: https://mitchellcarey.github.io/may-2026-election-correlations/

```
.
├── docs/                               # Deployed by GitHub Pages, no build step
│   ├── index.html                      # Winners — census × who-won-each-ward correlations
│   ├── changes.html                    # Changes — census × who-flipped-each-ward correlations
│   ├── map.html                        # Map — choropleth of GM wards
│   ├── current.html                    # Current — every council's most-recent winner
│   ├── shared.css                      # Shared styling for all four pages
│   └── uk/                             # GB-wide siblings of map.html + current.html
├── data/
│   ├── *.json                          # Generated intermediates (committed)
│   └── source/                         # Inputs — see "Required source data" below
└── scripts/                            # 33 numbered scripts across four pipelines
                                        # (Winners 01–08, Changes 00/01b/04b/05b/05c/06b/07b,
                                        #  Map 09/09b/09c/09d/07c, Current 10/11/04c/07d,
                                        #  Official 12/13, Holyrood 17/18). Full pipeline
                                        #  graph + re-run rules live in CLAUDE.md.
```

## Setup

- Python 3.10+
- `python -m venv .venv && source .venv/bin/activate`
- `pip install -r requirements.txt`

`geopandas` / `shapely` / `pyproj` in `requirements.txt` are build-only —
they're only needed if you rebuild ward boundaries with script 09 (or the
related 09b/09c/09d). The deployed artifacts ship as static HTML + JSON
and need none of them at runtime.

## Required source data

Two categories: manual downloads you fetch once, and caches that the build
scripts populate on first run. Everything below is gitignored.

**Manual (one-time, you download these):**

8 ONS Census 2021 ward XLSXs + 1 small-area income XLSX. Drop them into
`data/source/` — see [data/source/README.md](data/source/README.md) for
the exact filenames and NOMIS / ONS download links.

**Fetched on demand (the build scripts download these on first run; all
idempotent / skip-if-cached):**

| Cached file(s) under `data/source/`               | Populated by | Approx. size       |
|---------------------------------------------------|--------------|--------------------|
| `oa21_msoa21_lookup.csv`, `oa21_wd24_lookup.csv`  | script 03b   | 5–10 MB each       |
| `wd_may_2024_uk_bgc_*.geojson`                    | script 09    | ~50 MB             |
| `ced_may_2025_en_bgc.geojson`                     | script 09b   | ~10 MB             |
| `lgbce/*.zip` + extracted shapefiles              | script 09c   | ~37 MB             |
| `spc_may_2026_sc_bgc.geojson`                     | script 09d   | ~5 MB              |
| `wiki_*.json` (prior winners, 2026 results, most-recent winners) | scripts 00 / 00b / 10 | hundreds of files, ~200 KB each |
| `official_*.{html,json,pdf}`                      | script 12    | varies per council |

First end-to-end run pulls everything (slow on a cold cache). Subsequent
runs hit the cache and skip the network.

Hand-curated CSVs that *are* committed under `data/source/` —
`county_official_2026.csv`, `ward_official_2026.csv`,
`ward_name_overrides.csv`, `current_ward_overrides.csv`,
`ced_name_overrides.csv`, `census2021-ts022-ward.csv`, `councils.yaml` —
supplement what the scrapers can do automatically. Don't delete them.

## Rebuild the four pages

Each page has its own pipeline. Quick reference (full re-run rules and
dependencies live in [CLAUDE.md](CLAUDE.md) under "Keeping the artifacts current"):

```
Winners  → docs/index.html
           scripts 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08

Changes  → docs/changes.html
           scripts 00 → 01b → 04b → 05b → 05c → 06b → 07b   (depends on Winners 04)

Map      → docs/map.html  +  docs/uk/map.html
           script 09 → 07c --region=gm and 07c --region=gb

Current  → docs/current.html  +  docs/uk/current.html
           scripts 10 → 11 → (optional 12 → 13 for official sources) → 04c
                    → 07d --region=gm and 07d --region=gb
```

CLAUDE.md also documents the LGBCE overlay (09c), Holyrood (17/18), and the
official-source parser registry under `scripts/_official_parsers/`.

## View locally

Each page is static HTML — open `docs/index.html` (or any other) directly
in a browser, no dev server required. To preview the full GitHub Pages
layout including the `docs/uk/` siblings with their relative paths, run a
static server from the repo root:

```bash
python -m http.server -d docs 8000
# then visit http://localhost:8000
```

## Methodology

**Election data.** Collected 7-9 May 2026 from each council's official results
page where available, otherwise from the most authoritative local source:

- Bolton, Oldham, Stockport, Trafford, Wigan: council websites
- Bury: Bury Times via Yahoo News
- Manchester: Manchester City Council + Northern Quota for late declarations
- Rochdale: Rochdale Times
- Salford: Salford Now / salfordmedia.co.uk
- Tameside: Tameside Correspondent

**Census data.** ONS Census 2021 ward-level data via UK Data Service (XLSX) and NOMIS (CSV):

- TS006 (population density)
- TS007 (single-year age, 101 categories)
- TS063 (occupation, 10 SOC categories)
- TS067 (highest qualification, 8 categories, ages 16+)
- TS054 (tenure, 9 categories)
- TS004 (country of birth, 12 categories)
- TS061 (method of travel to work, 12 categories)
- TS008 (sex)
- TS022 (ethnic group, detailed — CSV)

**Aggregations:**
- `pct_apprentice` = TS067 code 3 / sum(0..6)
- `pct_level4_plus` = TS067 code 5 / sum(0..6)
- `pct_owned` = TS054 codes 0+1+2 (outright + mortgage + shared ownership)
- `pct_social_rented` = TS054 codes 3+4
- `pct_private_rented` = TS054 codes 5+6+7 (incl. lives-rent-free)
- `pct_uk_born` = TS004 code 1 / total
- `pct_wfh` = TS061 code 1 / sum(1..11) — employed-only denominator
- `pct_white` / `pct_asian` / `pct_black` / `pct_mixed` / `pct_other_ethnic` = TS022 top-level group sub-totals / TS022 'All usual residents'. `pct_black` combines the African and Caribbean Black sub-groups per the standard ONS 5-category presentation.
- `pct_soc123` = TS063 codes 1+2+3 / sum(1..9) — graduate-level jobs share

**Boundary mismatches.** Bolton (2023), Stockport (2023), Trafford (2023), and
Wigan (2024) had ward boundary reviews after Census 2021. Where 2026 ward names
match 2021 boundaries, exact GSS lookup is used. Where names changed but
boundaries are substantially the same, fuzzy mapping is applied (~33 wards).
Where 2026 wards are splits or significant rebounds of 2021 wards, an
approximate proxy is used (e.g. Farnworth North + South both inherit
2021's "Farnworth" Census profile). Approximate matches are flagged with `≈`
in the artifact's ward listing.

**Coverage.** 213 of 214 wards declared. Manchester's Miles Platting & Newton
Heath was still pending at time of analysis. Bury's Moorside ward election was
cancelled in April 2026 after the Reform candidate died (rerun expected June).
Salford's Cadishead & Lower Irlam had two seats up; counted once.

**Correlations.** Pearson r between a 0/1 party-win indicator and each
structural variable, computed across the full 213-ward declared sample.
Conservative (n=11) and LibDem (n=19) samples are smaller — read those r
values as direction-of-pattern rather than precise effect size. Independent
(n=9) and Other (n=6, mostly Workers Party + Oldham Group + Radcliffe First
+ community parties) are too heterogeneous to show clear structural patterns.

## Caveats

- This is a structural analysis, not a causal one. The correlations describe
  which wards Reform won, not why people voted Reform.
- `% apprenticeship` is the strongest signal but it sits in a cluster with
  `% UK-born`, `% 50-64`, low degree-holding, low WFH — Reform's territory is
  the post-industrial, older, non-graduate periphery.
- Census 2021 data is now ~5 years old; some inner-city wards have densified
  significantly since.
- Council Tax Support data is Manchester-only. Other boroughs run separate
  Council Tax Reduction schemes that aren't directly comparable.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

Built with [Claude Code](https://claude.com/claude-code).
Census data © Crown copyright, Office for National Statistics, used under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/).
