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
├── docs/
│   └── index.html                      # Final deliverable — served by GitHub Pages
├── data/
│   ├── all_gm_results.json             # 2026 election winners, per ward
│   ├── all_gm_gss_mapping.json         # Ward-name → ONS GSS code
│   ├── all_gm_census.json              # Census 2021 vars, per ward
│   ├── gm_all_wards.json               # Consolidated 214-ward dataset
│   ├── gm_correlations.json            # Pearson r and party means
│   ├── v12_ward_data.json              # JS-ready ward array
│   ├── combined_wards.json             # Snapshot: Manchester + Salford
│   ├── wards_v6.json                   # Snapshot: Manchester w/ CTS
│   └── source/                         # Place to drop ONS XLSX files
└── scripts/
    ├── 01_build_results.py             # Encode 2026 election results
    ├── 02_match_gss.py                 # Map ward names to GSS codes
    ├── 03_extract_census.py            # Pull from 8 ONS XLSX files
    ├── 04_consolidate.py               # Merge into single dataset
    ├── 05_correlate.py                 # Compute Pearson r and means
    ├── 06_prep_artifact_data.py        # Build JS-ready data
    └── 07_build_artifact.py            # Splice into docs/index.html
```

## Reproduce

```bash
pip install -r requirements.txt

# Drop the 8 ONS Census 2021 XLSX files into data/source/
# (see data/source/README.md for download links)

# Run the pipeline
python scripts/01_build_results.py
python scripts/02_match_gss.py
python scripts/03_extract_census.py
python scripts/04_consolidate.py
python scripts/05_correlate.py
python scripts/06_prep_artifact_data.py
python scripts/07_build_artifact.py
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
