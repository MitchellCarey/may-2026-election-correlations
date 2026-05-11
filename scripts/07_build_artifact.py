"""Splice the generated data + renderer JS into docs/index.html.

Replaces everything between the BEGIN GENERATED / END GENERATED markers
inside the page's single <script> block, in place. Run this whenever
upstream data changes — no other steps are needed before pushing.
"""
import json
import re
from pathlib import Path

from _artifact_lib import (
    corr_labels_js_quoted_keys,
    party_colours_text_js,
    party_display_text_js,
    party_order_winners_js,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

BEGIN = "// ===== BEGIN GENERATED — see scripts/07_build_artifact.py ====="
END = "// ===== END GENERATED ====="

with open(DATA / 'v12_ward_data.json') as f:
    wards = json.load(f)
with open(DATA / 'gm_correlations.json') as f:
    corr_full = json.load(f)

# Build compact RAW data structure: keyed by "Borough::Ward"
raw = {}
for w in wards:
    key = f"{w['borough']}::{w['ward']}"
    # Use compact field names matching v11 conventions where possible
    raw[key] = {
        'b': w['borough'],
        'wn': w['ward'],
        'w': w['winner'],
        's': w.get('turnout'),  # winner share not available for most; use turnout for sortability
        'd': w.get('density'),
        'med': w.get('median_age'),
        'a18': w.get('pct_under18'),
        'a29': w.get('pct_18_29'),
        'a49': w.get('pct_30_49'),
        'a64': w.get('pct_50_64'),
        'a65': w.get('pct_65plus'),
        'ap': w.get('pct_apprentice'),
        'l4': w.get('pct_level4_plus'),
        'soc': w.get('pct_soc123'),
        'ow': w.get('pct_owned'),
        'sr': w.get('pct_social_rented'),
        'pr': w.get('pct_private_rented'),
        'uk': w.get('pct_uk_born'),
        'wfh': w.get('pct_wfh'),
        'f': w.get('pct_female'),
        'm': w.get('match_type', 'mcr-orig'),  # data source/match type
    }

# Build new corrData: full GM correlations only
# Map: variable -> {party: r}
corrData = {}
for party, vars_dict in corr_full['correlations'].items():
    for var, r in vars_dict.items():
        if var == 'n_wards':
            continue
        if var not in corrData:
            corrData[var] = {}
        corrData[var][party] = r

# Build means data
means_full = corr_full['means']

# Borough tallies for borough-list rendering
borough_tallies = {}
for w in wards:
    b = w['borough']
    if b not in borough_tallies:
        borough_tallies[b] = {'wards': 0, 'parties': {}}
    borough_tallies[b]['wards'] += 1
    p = w['winner'] or 'Pending'
    borough_tallies[b]['parties'][p] = borough_tallies[b]['parties'].get(p, 0) + 1

# Generate JS
js_lines = []
js_lines.append('const RAW = ' + json.dumps(raw, separators=(',', ':')) + ';')
js_lines.append('const data = { wards: {} };')
js_lines.append('Object.entries(RAW).forEach(([k,v]) => {')
js_lines.append('  data.wards[k] = {')
js_lines.append('    key: k, borough: v.b, ward: v.wn, winner: v.w, turnout: v.s,')
js_lines.append('    density: v.d, median_age: v.med,')
js_lines.append('    pct_under18: v.a18, pct_18_29: v.a29, pct_30_49: v.a49,')
js_lines.append('    pct_50_64: v.a64, pct_65plus: v.a65,')
js_lines.append('    pct_apprentice: v.ap, pct_level4_plus: v.l4, pct_soc123: v.soc,')
js_lines.append('    pct_owned: v.ow, pct_social_rented: v.sr, pct_private_rented: v.pr,')
js_lines.append('    pct_uk_born: v.uk, pct_wfh: v.wfh, pct_female: v.f,')
js_lines.append('    match_type: v.m,')
js_lines.append('  };')
js_lines.append('});')
js_lines.append('')
js_lines.append(corr_labels_js_quoted_keys())
js_lines.append('')
js_lines.append('const corrData = ' + json.dumps(corrData, separators=(',', ':')) + ';')
js_lines.append('')
js_lines.append('const meansData = ' + json.dumps(means_full, separators=(',', ':')) + ';')
js_lines.append('')
# Convert party tallies to JSON for borough list
js_lines.append('const boroughTallies = ' + json.dumps(borough_tallies, separators=(',', ':')) + ';')
js_lines.append('')

# Now the rendering helpers
js_lines.append('\n'.join([
    '',
    party_colours_text_js(),
    party_display_text_js(other_label='Workers / Oldham Group / etc.'),
    party_order_winners_js(),
    '',
]))

# Correlation table renderer
js_lines.append('''
/* ===== CORRELATION TABLE ===== */
const corrBody = document.getElementById("corr-body");
const corrParties = ["Green","Labour","Reform","LibDem","Conservative"];
// Build header row
const corrHeadRow = document.querySelector("#corr-head tr") || document.querySelector(".corr-table thead tr");
if (corrHeadRow) {
  // Replace columns with Reform/Green/Labour/LibDem/Conservative
  corrHeadRow.innerHTML = "<th>Variable</th>" + corrParties.map(p => {
    const n = (meansData[p] && meansData[p].n) || "—";
    const cls = p.toLowerCase();
    return `<th class="${cls}-col">${partyDisplay[p]}<div style="font-size:10px;font-weight:400;letter-spacing:0;color:var(--muted);text-transform:none;">n=${n}</div></th>`;
  }).join("");
}
const corrVarOrder = [
  "density","median_age","pct_under18","pct_18_29","pct_30_49","pct_50_64","pct_65plus",
  "pct_apprentice","pct_level4_plus","pct_soc123","pct_no_qual",
  "pct_uk_born","pct_private_rented","pct_social_rented","pct_owned","pct_wfh","pct_female"
];
corrVarOrder.forEach((key) => {
  if (!corrData[key]) return;
  const row = document.createElement("tr");
  let cells = `<td class="corr-var">${corrLabels[key] || key}</td>`;
  cells += corrParties.map(party => {
    const r = corrData[key][party];
    if (r === undefined || r === null) {
      return `<td class="corr-cell" style="color:var(--muted);text-align:center">—</td>`;
    }
    const sign = r >= 0 ? "+" : "−";
    const abs = Math.abs(r);
    const cls = r >= 0 ? "pos" : "neg";
    const strong = abs > 0.4 ? "strong" : abs > 0.25 ? "med" : "weak";
    // Heatmap fill: opacity proportional to |r|, capped so the value
    // stays readable. Replaces the previous magnitude-sized .bar that
    // wouldn't align with the value text at small |r|.
    const opacity = Math.min(0.45, abs * 0.7);
    const tone = r >= 0 ? `44,140,79` : `200,54,42`;
    return `<td class="corr-cell ${cls} ${strong}" style="background:rgba(${tone},${opacity.toFixed(3)})"><span class="val">${sign}${abs.toFixed(3)}</span></td>`;
  }).join("");
  row.innerHTML = cells;
  corrBody.appendChild(row);
});
''')

# Means cards renderer
js_lines.append('''
/* ===== PARTY MEANS CARDS ===== */
const meansGrid = document.getElementById("means-grid");
const meansLabels = {
  density: "Density / km²",
  median_age: "Median age",
  pct_18_29: "% 18-29",
  pct_65plus: "% 65+",
  pct_apprentice: "% Apprentice",
  pct_level4_plus: "% Degree (L4+)",
  pct_soc123: "% SOC 1-3 jobs",
  pct_owned: "% Owned",
  pct_private_rented: "% Private rent",
  pct_social_rented: "% Social housing",
  pct_uk_born: "% UK-born",
  pct_wfh: "% WFH",
  pct_female: "% Female",
};
// Sort by sample size descending for visual heft
const meansPartyOrder = ["Reform","Green","Labour","LibDem","Conservative"];
meansPartyOrder.forEach(party => {
  const m = meansData[party];
  if (!m) return;
  const card = document.createElement("div");
  card.className = "means-card";
  let rows = "";
  Object.entries(meansLabels).forEach(([k, l]) => {
    const v = m[k];
    if (v === undefined || v === null) return;
    const display = k === "median_age" ? v.toFixed(2) + " yrs"
                  : k === "density"    ? Math.round(v).toLocaleString()
                  : v.toFixed(2) + "%";
    rows += `<div class="row"><span class="lbl">${l}</span><span class="val">${display}</span></div>`;
  });
  card.innerHTML = `
    <div class="pname"><span class="swatch" style="background:${partyColors[party]}"></span>${partyDisplay[party]}</div>
    <div class="pcount">${m.n} ward${m.n !== 1 ? "s" : ""} · GM-wide mean</div>
    ${rows}
  `;
  meansGrid.appendChild(card);
});
''')

# Borough list renderer
js_lines.append('''
/* ===== BOROUGH BREAKDOWN ===== */
const boroughList = document.getElementById("borough-list");
if (boroughList) {
  const boroughOrder = ["Manchester","Salford","Bolton","Bury","Oldham","Rochdale","Stockport","Tameside","Trafford","Wigan"];
  // Per-borough turnout headlines (where published or computable)
  // Manchester: weighted from per-ward electorate × turnout on the council results
  // page (sum matches declared 399,451 electorate).
  // Salford and Bolton councils have not published per-ward votes-cast totals,
  // so a borough-wide figure cannot be computed reliably yet.
  const boroughTurnouts = {
    "Bury": "45%",
    "Manchester": "32.5%",
    "Stockport": "44%",
    "Oldham": "46.6%",
    "Rochdale": "39.2%",
    "Trafford": "48.9%",
  };
  // Per-borough notes
  const boroughNotes = {
    "Bolton": "2023 boundaries · 7 fuzzy-mapped wards",
    "Stockport": "2023 boundaries · 5 fuzzy-mapped wards",
    "Trafford": "2023 boundaries · 12 fuzzy-mapped wards",
    "Wigan": "2024 boundaries · 8 fuzzy-mapped wards",
    "Manchester": "1 ward still pending",
    "Bury": "1 ward cancelled (Moorside)",
    "Salford": "Cadishead had 2 seats up; counted once",
  };
  boroughOrder.forEach(b => {
    const t = boroughTallies[b];
    if (!t) return;
    const block = document.createElement("div");
    block.className = "borough-block";
    // Sort parties by count desc
    const partySorted = Object.entries(t.parties).sort(([,a],[,b]) => b - a);
    const pills = partySorted.map(([p, n]) => {
      const color = partyColors[p] || "#999";
      return `<span class="b-pill" style="background:${color}">${partyDisplay[p] || p} ${n}</span>`;
    }).join(" ");
    const turnout = boroughTurnouts[b] ? `<span class="b-turnout">turnout ${boroughTurnouts[b]}</span>` : "";
    const note = boroughNotes[b] ? `<span class="b-note">${boroughNotes[b]}</span>` : "";
    block.innerHTML = `
      <div class="b-head">
        <span class="b-name">${b}</span>
        <span class="b-count">${t.wards} ward${t.wards !== 1 ? "s" : ""}</span>
        ${turnout}
      </div>
      <div class="b-pills">${pills}</div>
      ${note ? `<div class="b-meta">${note}</div>` : ""}
    `;
    boroughList.appendChild(block);
  });
}
''')

# Top correlations per party (§3)
js_lines.append('''
/* ===== TOP CORRELATIONS PER PARTY (§3) ===== */
const partyCorrGrid = document.getElementById("party-corr-grid");
if (partyCorrGrid) {
  const pcorrParties = ["Reform","Green","Labour","LibDem","Conservative"];
  const ageVars = new Set(["median_age","pct_under18","pct_18_29","pct_30_49","pct_50_64","pct_65plus"]);
  const dedupeAge = (arr) => {
    let used = false;
    return arr.filter(x => {
      if (!ageVars.has(x.variable)) return true;
      if (used) return false;
      used = true;
      return true;
    });
  };
  pcorrParties.forEach(party => {
    const rows = [];
    Object.entries(corrData).forEach(([variable, partyMap]) => {
      const r = partyMap[party];
      if (r === undefined || r === null) return;
      rows.push({ variable, r });
    });
    const pos = dedupeAge(rows.filter(x => x.r > 0).sort((a,b) => b.r - a.r)).slice(0, 5);
    const neg = dedupeAge(rows.filter(x => x.r < 0).sort((a,b) => a.r - b.r)).slice(0, 5);
    const card = document.createElement("div");
    card.className = "pcorr-card";
    const n = (meansData[party] && meansData[party].n) || "—";
    const fmt = (r) => {
      const sign = r >= 0 ? "+" : "−";
      return `${sign}${Math.abs(r).toFixed(2)}`;
    };
    const renderCol = (label, items, kind) => `
      <div>
        <div class="pcorr-col-label ${kind}">${label}</div>
        ${items.map(x => `
          <div class="pcorr-row">
            <span class="pcorr-r ${kind}">${fmt(x.r)}</span>
            <span class="pcorr-var">${corrLabels[x.variable] || x.variable}</span>
          </div>
        `).join("")}
      </div>
    `;
    card.innerHTML = `
      <div class="pcorr-head">
        <span class="pcorr-swatch" style="background:${partyColors[party]}"></span>
        <span class="pcorr-name">${partyDisplay[party]}</span>
        <span class="pcorr-n">n=${n}</span>
      </div>
      <div class="pcorr-cols">
        ${renderCol("Top positive correlations", pos, "pos")}
        ${renderCol("Top negative correlations", neg, "neg")}
      </div>
    `;
    partyCorrGrid.appendChild(card);
  });
}
''')

# Ward list renderer (group by borough → party)
js_lines.append('''
/* ===== ALL WARDS LIST (grouped by borough → party) ===== */
const wardsList = document.getElementById("wards-list");
if (wardsList) {
  const boroughOrder = ["Manchester","Salford","Bolton","Bury","Oldham","Rochdale","Stockport","Tameside","Trafford","Wigan"];
  // Group by borough
  const byBorough = {};
  Object.values(data.wards).forEach(w => {
    if (!byBorough[w.borough]) byBorough[w.borough] = [];
    byBorough[w.borough].push(w);
  });
  boroughOrder.forEach(borough => {
    const bWards = byBorough[borough];
    if (!bWards) return;
    const block = document.createElement("div");
    block.className = "borough-ward-block";
    const tallyTxt = Object.entries(boroughTallies[borough].parties).sort(([,a],[,b]) => b - a)
      .map(([p,n]) => `<span style="color:${partyColors[p]||'#999'};font-weight:600;">${p} ${n}</span>`).join(" · ");
    block.innerHTML = `
      <div class="bward-head">
        <span class="bward-name">${borough}</span>
        <span class="bward-tally">${tallyTxt}</span>
      </div>
    `;
    // Column header strip — clarifies what the four numeric columns mean.
    const headRow = document.createElement("div");
    headRow.className = "ward-row mini head";
    headRow.innerHTML = `
      <span class="name">Ward</span>
      <span>Winner</span>
      <span class="num" title="Population per km²">Density</span>
      <span class="num" title="% with Level 4+ qualification (degree)">% Degree</span>
      <span class="num col-hide-mobile" title="% with apprenticeship">% Appr.</span>
      <span class="num col-hide-mobile" title="% UK-born">% UK-born</span>
    `;
    block.appendChild(headRow);
    // Sort wards by party order then density desc
    bWards.sort((a, b) => {
      const ai = partyOrder.indexOf(a.winner);
      const bi = partyOrder.indexOf(b.winner);
      if (ai !== bi) return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
      return (b.density || 0) - (a.density || 0);
    });
    bWards.forEach(w => {
      const row = document.createElement("div");
      row.className = "ward-row mini";
      const winColor = partyColors[w.winner] || "#999";
      const dens = w.density != null ? (w.density / 1000).toFixed(1) + "k" : "—";
      const l4 = w.pct_level4_plus != null ? w.pct_level4_plus.toFixed(0) + "%" : "—";
      const ap = w.pct_apprentice != null ? w.pct_apprentice.toFixed(1) + "%" : "—";
      const uk = w.pct_uk_born != null ? w.pct_uk_born.toFixed(0) + "%" : "—";
      const fuzzyMark = w.match_type && w.match_type !== "exact" && w.match_type !== "mcr-orig" ? '<span class="fuzz" title="approximate Census mapping (boundary change)">≈</span>' : "";
      row.innerHTML = `
        <span class="name">${w.ward}${fuzzyMark}</span>
        <span class="winpill" style="background:${winColor}">${w.winner}</span>
        <span class="num">${dens}</span>
        <span class="num">${l4}</span>
        <span class="num col-hide-mobile">${ap}</span>
        <span class="num col-hide-mobile">${uk}</span>
      `;
      block.appendChild(row);
    });
    wardsList.appendChild(block);
  });
}
''')

new_js = '\n'.join(js_lines)

# Splice into docs/index.html between the BEGIN/END markers.
html_path = DOCS / 'index.html'
html = html_path.read_text()
pattern = re.compile(
    re.escape(BEGIN) + r'\n.*?\n' + re.escape(END),
    re.DOTALL,
)
matches = pattern.findall(html)
if len(matches) != 1:
    raise SystemExit(
        f"Expected exactly one BEGIN/END marker pair in {html_path}, "
        f"found {len(matches)}. Add the markers around the generated "
        f"<script> block before re-running."
    )
new_html = pattern.sub(lambda _m: BEGIN + '\n' + new_js + '\n' + END, html, count=1)
html_path.write_text(new_html)

print(f"Spliced {len(new_js)} chars of generated JS into {html_path.relative_to(ROOT)}")
print(f"  RAW entries: {len(raw)}")
print(f"  corrData variables: {len(corrData)}")
print(f"  meansData parties: {list(means_full.keys())}")
