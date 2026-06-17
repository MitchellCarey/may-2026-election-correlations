# UK election coverage on the Current map

A complete catalogue of every UK election held 2010–2026, with each marked against the **Current map's** time slider on [docs/uk/current.html](uk/current.html).

Today the slider has **11 year stops**: `[2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026]`.

## Legend

| Marker | Meaning |
|---|---|
| **✓** | Fully painted on the slider at this year |
| **◐** | Partial — some councils/seats present, others missing or grey |
| **✗** | Missing — not on the slider |
| **N/A** | No election of this type occurred this year |

Effort estimates for the missing rows:

| Effort | Roughly means |
|---|---|
| **easy** | Sits inside an existing pipeline shape — one parser + one history pass. Days, not weeks. |
| **medium** | Needs a new polygon era or a new pipeline limb (fetcher + extractor + history) but reuses an existing pattern. |
| **hard** | Needs new infrastructure — a new viewBox, a date axis, or a results source that doesn't exist centrally. |

---

## 1. Westminster General Elections

| Date | Coverage | Notes |
|---|---|---|
| 6 May 2010 | **✗** (easy–medium) | HoC Library CBP-8647 also publishes 2010 (verify XLSX has a 2010 sheet). 2010 boundaries match `PCON21` for 645/650 seats — same polygon era as 2015/2017/2019. If CBP-8647 carries 2010: extend `20b_extract_ge_history.py` to read a fourth sheet. Adds a `2010` slider stop. |
| 7 May 2015 | **✓** | `20b_extract_ge_history.py` + `21b_fetch_pcon_2010_geoms.py` (#71 phase 1E). |
| 8 Jun 2017 | **✓** | Same pipeline. |
| 12 Dec 2019 | **✓** | Same pipeline. |
| 4 Jul 2024 | **✓** | `19/20/21` GE 2024 overlay, `PCON24` polygons. |
| (next GE) | N/A | Next GE expected by 2029. |

---

## 2. Scottish Parliament (Holyrood)

| Date | Coverage | Notes |
|---|---|---|
| 5 May 2011 | **✗** (medium) | 73 constituencies + 8 regional lists. 2011 boundaries pre-date the 2014 review used by `PRE_<SPC22CD>` — would need a third polygon era (`PRE2_<SPC11CD>`). Per-constituency wiki articles cover 2011 via the same `{{AMS election box}}` template the existing `18b` parser handles. |
| 5 May 2016 | **✓** | `04f_build_holyrood_history.py` + `09f_overlay_pre_review_holyrood.py` (#74 phase 1C). |
| 6 May 2021 | **✓** | Same pipeline. |
| 7 May 2026 | **✓** | `04c` Pass 1a + `17/18` consolidated parser. |
| **Regional-list MSPs** (2011/2016/2021/2026) | **◐** (easy) | Constituency layer paints the FPTP winner only. Regional-list seats are visible in the source articles but not yet surfaced in `04f` output. Pattern is identical to Senedd's `SENEDD_REGION_HISTORY` (`04g`). |

---

## 3. Welsh Parliament (Senedd Cymru)

Pre-2020 known as the National Assembly for Wales.

| Date | Coverage | Notes |
|---|---|---|
| 5 May 2011 | **✗** (easy) | 40 NAWC constituencies + 5 PR regions. Boundaries unchanged since 2006 → `NAWC21` polygons (already shipped via `16b`) are valid for 2011. Only the history extraction is missing: extend `14b/15b/04g` to also crawl 2011 election boxes per constituency + per region. **Cheapest gap on the map.** |
| 5 May 2016 | **✓** | Phase 1D / #72. |
| 6 May 2021 | **✓** | Same pipeline. |
| 7 May 2026 | **✓** | First election under 96-member / 16-constituency closed-list reform. |

---

## 4. Northern Ireland Assembly (Stormont)

| Date | Coverage | Notes |
|---|---|---|
| 5 May 2011 | **✗** (hard) | 18 constituencies, 108 MLAs, STV. NI is **excluded from the GB viewBox** — would need a separate NI viewBox / page or a UK-wide projection. NIA constituencies are coterminous with PCON NI codes through 2017. |
| 5 May 2016 | **✗** (hard) | Same. |
| 2 Mar 2017 | **✗** (hard) | Early election; new 5-MLA cap → 90 MLAs across same 18 constituencies. |
| 5 May 2022 | **✗** (hard) | Same constituencies as 2017. |

**Status:** the whole NI layer is absent from the project today. Defer until a UK viewBox is added. If we ever add it, the Westminster PCON 2024 NI 18 seats (currently fetched but filtered at render time in `07d`) would light up automatically.

---

## 5. English local elections

Wards are painted from `wiki_current_articles` in `data/source/councils.yaml` and `04d_build_ward_history.py`. WD24 boundaries are used uniformly; pre-WD24 contests need a per-council polygon era — see effort notes below.

### 5a. London boroughs (32, 4-yr cycle)

| Date | Coverage | Notes |
|---|---|---|
| 6 May 2010 | **✗** (medium) | Per-borough WD2010 polygon era needed; per-borough wiki articles exist. |
| 22 May 2014 | **✗** (medium) | Mostly WD pre-2024 era; several boroughs unchanged. |
| 3 May 2018 | **✓** | `wiki_current_articles` + `04d`. |
| 5 May 2022 | **✓** | Same. |
| 7 May 2026 | **✓** | Pass 1a of `04c` (Wikipedia → `all_wards.json`); some boroughs upgraded to ModernGov scrape via `13_extract_official.py` (#36). |

### 5b. Metropolitan boroughs (36 — Greater Manchester, Merseyside, S/W Yorkshire, Tyne & Wear, W Midlands)

Mostly thirds (elect a third per year); some all-out.

| Date | Coverage | Notes |
|---|---|---|
| 6 May 2010 | **✗** (medium–hard) | WD24 mismatch in many districts (Tameside, Rochdale, etc. boundary-reviewed since). |
| 5 May 2011 | **✗** (medium) | Same. |
| 3 May 2012 | **✗** (medium) | Same. |
| 2 May 2013 | **✗** (medium) | Some mets had no contest (county year for unitaries; mets in shadow). |
| 22 May 2014 | **✗** (medium) | Same. |
| 7 May 2015 | **✗** (medium) | Same. |
| 5 May 2016 | **✗** (medium) | Same. |
| 4 May 2017 | **◐** | Some present via `wiki_current_articles`; not uniform across all 36. |
| 3 May 2018 | **✓** | Uniformly, #69 phase 1A. |
| 2 May 2019 | **✓** | Same. |
| 6 May 2021 | **✓** | Same. |
| 5 May 2022 | **✓** | Same. |
| 4 May 2023 | **✓** | Same. |
| 2 May 2024 | **✓** | Same. |
| 7 May 2026 | **✓** | Pass 1a of `04c` + ModernGov / bespoke parsers via #36 / #9 phase 4 (Bolton, Manchester, Oldham, Rochdale, Salford, Stockport, Tameside, Trafford, Wigan). Bury deferred (Contensis SPA, no parser yet). |

### 5c. English unitary authorities (~62, mixed cycles)

| Date | Coverage | Notes |
|---|---|---|
| 2010 → 2017 | **✗** (medium per council) | 50+ separate wiki articles per year; mixed boundary review status; one polygon era per council. |
| 2018 → 2026 | **✓** | Within slider range via `wiki_current_articles`; new 2025-all-out boundary-review unitaries (Durham, Bucks, W/N Northamptonshire, Northumberland, Shropshire) covered via `current_ward_overrides.csv`. |

### 5d. English shire districts (~164, mostly all-out 4-yr)

| Date | Coverage | Notes |
|---|---|---|
| Pre-2018 | **✗** (medium–hard) | Largest count of councils; many boundary reviews; would dwarf existing `04d` output. |
| 2018 → 2026 | **✓** | Within slider range. |

### 5e. English county councils (21, 4-yr all-out)

| Date | Coverage | Notes |
|---|---|---|
| 2 May 2013 | **✗** (hard) | Would need a third CED polygon era — pre-2017 boundaries differ in several counties; HoC Library local-election handbooks could source. The existing pre-review CED polygons in `09e_overlay_pre_review_ceds.py` only cover Norfolk/Essex/Suffolk/Surrey for the 2017+2021 era. |
| 4 May 2017 | **✓** | #69 phase 1B / #73 — `04e_build_ced_history.py`. |
| 6 May 2021 | **✓** | Same. |
| 4 May 2025 | **✓** | `07d` summary line. |
| 7 May 2026 | **✓** | Devolution-priority 6 counties; `13_extract_official.py` parsers (Hampshire, Suffolk, etc.). |

---

## 6. Scottish local elections (32 councils, 5-yr all-out STV)

| Date | Coverage | Notes |
|---|---|---|
| 5 May 2011 | **✗** (medium) | Ward boundaries differ from WD24 in many councils; the STV parser `parse_stv_article` already exists. |
| 4 May 2017 | **◐** | Some councils in `wiki_current_articles`; not all 32. |
| 5 May 2022 | **✓** | |
| 7 May 2026 | **✓** | |

---

## 7. Welsh principal-area (unitary) elections (22, 5-yr all-out)

| Date | Coverage | Notes |
|---|---|---|
| 3 May 2012 | **✗** (medium) | Pre-WD24 boundaries widespread. |
| 4 May 2017 | **◐** | Partial via `wiki_current_articles`; `current_ward_overrides.csv` handles some Welsh pre-WD24 drift. |
| 5 May 2022 | **✓** | |
| 7 May 2026 | **✓** | |

---

## 8. Northern Ireland local elections

11 councils since 2014; 26 pre-2014.

| Date | Coverage | Notes |
|---|---|---|
| 5 May 2011 | **✗** (hard) | 26-council era. NI not on the map. |
| 22 May 2014 | **✗** (hard) | First 11-council election under new boundaries. |
| 2 May 2019 | **✗** (hard) | Same boundaries. |
| 18 May 2023 | **✗** (hard) | Same. |

Blocked by the same NI viewBox absence as Stormont.

---

## 9. London Mayor & London Assembly (GLA)

| Date | Coverage | Notes |
|---|---|---|
| 3 May 2012 | **✗** (easy mayor / medium assembly) | Mayor: one Greater London polygon, single winner. Assembly: 14 FPTP constituencies (stable since 2000) + 11 London-wide list. Could ship as a top-bar toggle alongside PCON/CED. |
| 5 May 2016 | **✗** (easy / medium) | Same. |
| 6 May 2021 | **✗** (easy / medium) | Postponed from 2020 under coronavirus regs. |
| 2 May 2024 | **✗** (easy / medium) | Mayor switched from SV to FPTP under Elections Act 2022. |

---

## 10. Combined-authority mayors (England)

One LAD-union polygon per CA + per-election winner. Structurally similar to the Surrey unitary overlay (`22/23/24`). Could land as one combined CA-mayor layer.

| CA / Mayor | Election years | Coverage |
|---|---|---|
| Greater Manchester | 2017, 2021, 2024 | **✗** (easy) |
| West Midlands | 2017, 2021, 2024 | **✗** (easy) |
| Liverpool City Region | 2017, 2021, 2024 | **✗** (easy) |
| Cambridgeshire & Peterborough | 2017, 2021, 2024 | **✗** (easy) |
| Tees Valley | 2017, 2021, 2024 | **✗** (easy) |
| West of England | 2017, 2021, 2024 | **✗** (easy) |
| Sheffield City Region / South Yorkshire | 2018, 2022, 2024 | **✗** (easy) |
| North of Tyne / North East (reformed 2024) | 2019, 2024 | **✗** (easy) |
| West Yorkshire | 2021, 2024 | **✗** (easy) |
| East Midlands | 2024 | **✗** (easy) |
| York & North Yorkshire | 2024 | **✗** (easy) |
| Hull & East Yorkshire | 2025 | **✗** (easy) |
| Greater Lincolnshire | 2025 | **✗** (easy) |

---

## 11. Directly-elected local mayors (non-CA)

Tower Hamlets, Lewisham, Newham, Hackney, Watford, Bedford, Bristol (until 2024 — abolished after referendum), Liverpool (until 2023 — abolished after referendum), Mansfield, Middlesbrough, North Tyneside, Doncaster, Salford, Croydon (since 2022), etc.

| | Coverage |
|---|---|
| All elections 2010–2026 | **✗** (easy each; ~15 cities × ~3 elections each ≈ 45 records). One LAD polygon per mayor. Could batch into the same mayoral layer as CA mayors. |

---

## 12. Police & Crime Commissioner (PCC)

England & Wales, 41 forces in 2024.

| Date | Coverage | Notes |
|---|---|---|
| 15 Nov 2012 | **✗** (medium) | Police-force-area polygons available from ONS; not coterminous with LADs. |
| 5 May 2016 | **✗** (medium) | Same. |
| 6 May 2021 | **✗** (medium) | Same. |
| 2 May 2024 | **✗** (medium) | Some forces' PCC role absorbed into the local CA mayor (GM, W Midlands, W Yorkshire, etc.) — drop out of this layer when absorbed. |

---

## 13. European Parliament elections

UK left the EU on 31 January 2020.

| Date | Coverage | Notes |
|---|---|---|
| 22 May 2014 | **✗** (medium) | 12 regional constituencies, d'Hondt list. EER polygons available from ONS. Render as "plurality winner" per region or as a small multi-pie. |
| 23 May 2019 | **✗** (medium) | Same. |

---

## 14. UK-wide referendums

| Date | Coverage | Notes |
|---|---|---|
| 5 May 2011 — AV referendum (UK-wide) | **✗** (hard) | Per-counting-area results (~440 areas). Could paint at LAD level. Outcome: 67.9% No. |
| 18 Sep 2014 — Scottish independence (Scotland) | **✗** (medium) | 32 council areas, single Yes/No outcome each. Easy to source, easy to render at LAD level. Outcome: 55.3% No. |
| 23 Jun 2016 — EU membership (UK-wide) | **✗** (medium) | Per-counting-area results published by Electoral Commission; ~382 areas. Could paint at LAD. **High visual payoff.** Outcome: 51.9% Leave. |

---

## 15. By-elections

| | Coverage |
|---|---|
| Westminster (~50 in period) | **✗** (hard) |
| Devolved parliaments (~20 in period) | **✗** (hard) |
| Local (thousands annually) | **✗** (hard) |

By-elections aren't natural on a year slider — they'd need a fine-grained date axis, or a separate "events" toggle that pulses a polygon at the by-election date. **Defer indefinitely.**

---

## 16. Parish/town council elections (England)

| | Coverage |
|---|---|
| ~10,000 parishes, mostly uncontested | **✗** (hard) |

Polygon set exists (parish boundaries on ONS) but results aren't centrally published. **Defer indefinitely.**

---

## 17. Community council elections (Wales/Scotland)

| | Coverage |
|---|---|
| Welsh community councils + Scottish community councils | **✗** (hard) |

Same as parish councils — no central results source. **Defer indefinitely.**

---

## "Easy wins" — prioritised by user-visible payoff

Gaps marked **easy** or **medium** in the body, sorted so the top of the list is what to do next.

| # | Gap | Effort | Payoff |
|---|---|---|---|
| 1 | **Senedd 2011** (constituency + regional list) | easy | medium — closes the only easy-effort missing election; adds a 2011 stop |
| 2 | **GLA Mayor 2012/2016/2021/2024** | easy | high — London is dense and politically visible |
| 3 | **Combined-authority mayors 2017–2025** | easy | high — 15+ regions, growing every cycle |
| 4 | **Holyrood + Senedd regional-list 2016/2021/2026** | easy | medium — regional MSPs/MSs visible in tooltip |
| 5 | **2010 General Election** | easy if CBP-8647 has a 2010 sheet | medium — adds another slider stop using existing PCON polygons |
| 6 | **2016 EU referendum (LAD-level)** | medium | high — politically resonant |
| 7 | **2014 Scottish independence referendum (LAD-level)** | medium | medium-high — politically resonant |
| 8 | **PCC 2012/2016/2021/2024** | medium | medium — 41 force areas E&W |
| 9 | **Welsh + Scottish local 2017 cleanup** | medium | medium — closes the slider's 2017 partial coverage |
| 10 | **GLA Assembly 2012/2016/2021/2024** | medium | medium — pairs with mayor layer |
| 11 | **Directly-elected city mayors** | easy each (~45 records) | medium — pairs with CA mayors |
| 12 | **EU Parliament 2014 + 2019** | medium | medium |
| 13 | **2011 AV referendum (LAD-level)** | medium | medium |
| 14 | **Holyrood 2011** | medium | medium — third polygon era required |
| 15 | **Pre-2018 metropolitan/unitary/district locals** | medium–hard | low — per-council polygon eras needed |
| 16 | **2013 county elections** | hard | medium — third CED polygon era |
| 17 | **Stormont + NI local (full NI coverage)** | hard | high — would unlock all NI |
| 18 | **Westminster by-elections** | hard | low — needs date axis |
| 19 | **Parish/community councils** | hard | low — no central results source |

---

## Cross-references

Where coverage already exists, the relevant scripts (in pipeline order):

- **Wards:** `scripts/04d_build_ward_history.py`
- **County divisions (CEDs):** `scripts/04e_build_ced_history.py`, `scripts/09e_overlay_pre_review_ceds.py`, `scripts/09c_overlay_lgbce_ceds.py`
- **Scottish Parliament:** `scripts/04f_build_holyrood_history.py`, `scripts/17b/18b_*.py`, `scripts/09f_overlay_pre_review_holyrood.py`
- **Welsh Parliament:** `scripts/04g_build_senedd_history.py`, `scripts/14b/15b_*.py`, `scripts/16b_fetch_senedd_2007_geoms.py`
- **Westminster:** `scripts/19/20/21_*.py` (GE 2024), `scripts/19b/20b/21b_*.py` (GE 2015/17/19 history)
- **Senedd 2026 overlay:** `scripts/14/15/16_*.py`
- **Surrey 2026 unitaries:** `scripts/22/23/24_*.py`
- **Renderer:** `scripts/07d_build_current_map_artifact.py`

See [CLAUDE.md](../CLAUDE.md) for the full pipeline-by-pipeline narrative including the phased build-out of the slider (#69 phases 1A–1E).
