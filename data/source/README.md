# Source data

This directory should contain 8 ONS Census 2021 ward-level XLSX files plus
one CSV (TS022). They are gitignored where large; the smaller TS022 CSV is
checked in since it's the only table the pipeline can't easily re-fetch
automatically.

## Required files

Drop these into this directory before running `scripts/03_extract_census.py`:

| Filename                                                          | Variable                  |
|-------------------------------------------------------------------|---------------------------|
| `TS006-Population-Density-2021-wd-ONS.xlsx`                       | Population density        |
| `TS007-Age-By-Single-Year-2021-wd-ONS.xlsx`                       | Age (101 categories)      |
| `TS063-Occupation-2021-wd-ONS.xlsx`                               | Occupation (10 SOC)       |
| `TS067-Highest-Level-Of-Qualification-2021-wd-ONS.xlsx`           | Highest qualification     |
| `TS054-Tenure-2021-wd-ONS.xlsx`                                   | Tenure (9 categories)     |
| `TS004-Country-Of-Birth-2021-wd-ONS.xlsx`                         | Country of birth          |
| `TS061-Method-Used-To-Travel-To-Work-2021-wd-ONS.xlsx`            | Method of travel to work  |
| `TS008-Sex-2021-wd-ONS.xlsx`                                      | Sex                       |
| `census2021-ts022-ward.csv`                                       | Ethnic group (detailed) — CSV (one row per ward, columns are the full ~290-category hierarchy under five top-level ONS groups) |

## Where to download

ONS publishes these as part of the Census 2021 dataset family. The easiest
route is via the **NOMIS** interface or the ONS bulk download service:

- **NOMIS** (recommended): https://www.nomisweb.co.uk/sources/census_2021_ts
  - Pick the dataset (e.g. TS006), filter to `Geography → Electoral wards
    and divisions (2021)`, download as XLSX.
- **ONS direct**: https://www.ons.gov.uk/datasets — search for the table
  reference (e.g. "TS006") and download the ward-level XLSX.

## Notes

- All 8 files cover England (and Wales for some). Greater Manchester wards
  use GSS codes in the range `E05000650–E05000680` (Manchester),
  `E05013018–E05013040` (Salford), and similar contiguous ranges per
  borough.
- File sizes are roughly 5-15 MB each.
- The pipeline expects the exact filenames above. If yours differ, either
  rename them or update the paths in `scripts/03_extract_census.py`.
