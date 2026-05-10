"""Splice the generated data + renderer JS into docs/changes.html.

Mirror of scripts/07_build_artifact.py for the Changes page. Reads:

  - data/v1_changes_ward_data.json  (compact ward array, from 06b)
  - data/gm_flip_correlations.json  (party × Census Pearson r, from 05b)

…and rewrites the block between the BEGIN/END markers in docs/changes.html
in place.

Reuses 07's correlation-matrix and per-party-card renderers verbatim — same
{var: {party: r}} shape, same .corr-frame / .pcorr-card CSS — and adds a new
borough-grouped flipped-wards appendix as §3.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

BEGIN = "// ===== BEGIN GENERATED — see scripts/07b_build_changes_artifact.py ====="
END = "// ===== END GENERATED ====="


def main():
    with open(DATA / 'v1_changes_ward_data.json') as f:
        wards = json.load(f)
    with open(DATA / 'gm_flip_correlations.json') as f:
        corr_full = json.load(f)

    # Compact RAW: keyed by "Borough::Ward"
    raw = {}
    for w in wards:
        key = f"{w['borough']}::{w['ward']}"
        raw[key] = {
            'b': w['borough'],
            'wn': w['ward'],
            'w': w.get('winner'),
            'pp': w.get('prior_party'),
            'py': w.get('prior_year'),
            'fl': w.get('flipped'),
            'mp': w.get('match_type_prior'),
            'd': w.get('density'),
            'l4': w.get('pct_level4_plus'),
            'ap': w.get('pct_apprentice'),
            'uk': w.get('pct_uk_born'),
        }

    # Re-pivot correlations: variable -> {party: r}
    corrData = {}
    for party, vars_dict in corr_full['correlations'].items():
        for var, r in vars_dict.items():
            if var == 'n_flipped':
                continue
            corrData.setdefault(var, {})[party] = r

    means = corr_full['means']

    # Parties with flip data, sorted by n_flipped descending. This drives column
    # order in §1 and card order in §2 — biggest sample first.
    flip_parties = sorted(
        corr_full['correlations'].keys(),
        key=lambda p: -corr_full['correlations'][p]['n_flipped'],
    )

    js_lines = []

    js_lines.append('const RAW = ' + json.dumps(raw, separators=(',', ':')) + ';')
    js_lines.append('const wards = Object.values(RAW).map(v => ({')
    js_lines.append('  borough: v.b, ward: v.wn, winner: v.w,')
    js_lines.append('  prior_party: v.pp, prior_year: v.py,')
    js_lines.append('  flipped: v.fl, match_type_prior: v.mp,')
    js_lines.append('  density: v.d, pct_level4_plus: v.l4,')
    js_lines.append('  pct_apprentice: v.ap, pct_uk_born: v.uk,')
    js_lines.append('}));')
    js_lines.append('')
    js_lines.append('const corrData = ' + json.dumps(corrData, separators=(',', ':')) + ';')
    js_lines.append('const meansData = ' + json.dumps(means, separators=(',', ':')) + ';')
    js_lines.append('const flipParties = ' + json.dumps(flip_parties) + ';')
    js_lines.append('')

    js_lines.append('''
const corrLabels = {
  density: "Population density (per km²)",
  median_age: "Median age (years)",
  pct_under18: "% aged under 18",
  pct_18_29: "% aged 18-29",
  pct_30_49: "% aged 30-49",
  pct_50_64: "% aged 50-64",
  pct_65plus: "% aged 65+",
  pct_apprentice: "% with apprenticeship",
  pct_level4_plus: "% with Level 4+ (degree)",
  pct_soc123: "% in SOC 1-3 (graduate-level jobs)",
  pct_no_qual: "% with no qualifications",
  pct_uk_born: "% born in UK",
  pct_private_rented: "% Private rent",
  pct_social_rented: "% Social housing",
  pct_owned: "% Owned",
  pct_wfh: "% Working from home",
  pct_female: "% Female",
};

const partyColors = {
  Green: "var(--green)",
  Reform: "var(--reform)",
  Labour: "var(--labour)",
  LibDem: "var(--libdem)",
  Conservative: "#1d4f8a",
  Independent: "#888",
  Other: "#a87b3e",
  Pending: "#bbb"
};
const partyDisplay = {
  Green: "Greens",
  Labour: "Labour",
  Reform: "Reform UK",
  LibDem: "Liberal Democrats",
  Conservative: "Conservatives",
  Independent: "Independent / local",
  Other: "Other",
  Pending: "Awaiting declaration"
};
const partyShort = {
  Green: "Green",
  Labour: "Labour",
  Reform: "Reform",
  LibDem: "LibDem",
  Conservative: "Cons",
  Independent: "Indep",
  Other: "Other",
  Pending: "Pending"
};
''')

    # § 1 matrix renderer — lifted from 07 with a small tweak: column header
    # subtitle reads "n_flipped=X" (not "n=X") so readers know the basis.
    js_lines.append('''
/* ===== § 1 — flip correlation matrix ===== */
const corrBody = document.getElementById("corr-body");
const corrHeadRow = document.querySelector("#corr-head tr");
if (corrHeadRow) {
  corrHeadRow.innerHTML = "<th>Variable</th>" + flipParties.map(p => {
    const n = (meansData[p] && meansData[p].n) || "—";
    const cls = p.toLowerCase();
    return `<th class="${cls}-col">${partyShort[p] || p}<div style="font-size:10px;font-weight:400;letter-spacing:0;color:var(--muted);text-transform:none;">flipped=${n}</div></th>`;
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
  cells += flipParties.map(party => {
    const r = corrData[key][party];
    if (r === undefined || r === null) {
      return `<td class="corr-cell" style="color:var(--muted);text-align:center">—</td>`;
    }
    const sign = r >= 0 ? "+" : "−";
    const abs = Math.abs(r);
    const cls = r >= 0 ? "pos" : "neg";
    const strong = abs > 0.4 ? "strong" : abs > 0.25 ? "med" : "weak";
    const opacity = Math.min(0.45, abs * 0.7);
    const tone = r >= 0 ? `44,140,79` : `200,54,42`;
    return `<td class="corr-cell ${cls} ${strong}" style="background:rgba(${tone},${opacity.toFixed(3)})"><span class="val">${sign}${abs.toFixed(3)}</span></td>`;
  }).join("");
  row.innerHTML = cells;
  corrBody.appendChild(row);
});
''')

    # § 2 per-party cards — same logic as 07 but reads from the flip dataset
    js_lines.append('''
/* ===== § 2 — top correlations per "flipped to" party ===== */
const partyCorrGrid = document.getElementById("party-corr-grid");
if (partyCorrGrid) {
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
  flipParties.forEach(party => {
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
    const fmt = (r) => (r >= 0 ? "+" : "−") + Math.abs(r).toFixed(2);
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
        <span class="pcorr-name">Flipped to ${partyDisplay[party]}</span>
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

    # § 3 flipped-wards appendix — borough-grouped list with prior → new
    js_lines.append('''
/* ===== § 3 — flipped wards appendix ===== */
const flippedList = document.getElementById("flipped-wards-list");
if (flippedList) {
  const boroughOrder = ["Manchester","Salford","Bolton","Bury","Oldham","Rochdale","Stockport","Tameside","Trafford","Wigan"];
  const partyOrder = ["Reform","Green","Labour","LibDem","Conservative","Independent","Other","Pending"];
  // Group by borough
  const byBorough = {};
  wards.forEach(w => {
    if (!byBorough[w.borough]) byBorough[w.borough] = [];
    byBorough[w.borough].push(w);
  });
  boroughOrder.forEach(borough => {
    const bWards = byBorough[borough];
    if (!bWards) return;
    // Sort: flipped first, then by 2026 winner party order, then by ward
    bWards.sort((a, b) => {
      const af = a.flipped ? 0 : (a.flipped === false ? 1 : 2);
      const bf = b.flipped ? 0 : (b.flipped === false ? 1 : 2);
      if (af !== bf) return af - bf;
      const ai = partyOrder.indexOf(a.winner || "Pending");
      const bi = partyOrder.indexOf(b.winner || "Pending");
      if (ai !== bi) return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
      return a.ward.localeCompare(b.ward);
    });
    const flipCount = bWards.filter(w => w.flipped).length;
    const heldCount = bWards.filter(w => w.flipped === false).length;
    const block = document.createElement("div");
    block.className = "borough-ward-block";
    block.innerHTML = `
      <div class="bward-head">
        <span class="bward-name">${borough}</span>
        <span class="bward-tally"><strong>${flipCount}</strong> flips · ${heldCount} holds${flipCount + heldCount !== bWards.length ? ` · ${bWards.length - flipCount - heldCount} pending/no-prior` : ""}</span>
      </div>
    `;
    // Header strip
    const headRow = document.createElement("div");
    headRow.className = "ward-row mini flip-row head";
    headRow.innerHTML = `
      <span class="name">Ward</span>
      <span>Prior</span>
      <span>2026</span>
      <span>Status</span>
      <span class="num col-hide-mobile" title="Population per km²">Density</span>
      <span class="num col-hide-mobile" title="% with Level 4+ qualification (degree)">% Degree</span>
      <span class="num col-hide-mobile" title="% UK-born">% UK-born</span>
    `;
    block.appendChild(headRow);
    bWards.forEach(w => {
      const row = document.createElement("div");
      row.className = "ward-row mini flip-row";
      const priorColor = w.prior_party ? (partyColors[w.prior_party] || "#999") : "#b6ad9c";
      const newColor = partyColors[w.winner] || "#999";
      const dens = w.density != null ? (w.density / 1000).toFixed(1) + "k" : "—";
      const l4 = w.pct_level4_plus != null ? w.pct_level4_plus.toFixed(0) + "%" : "—";
      const uk = w.pct_uk_born != null ? w.pct_uk_born.toFixed(0) + "%" : "—";
      const fuzz = (w.match_type_prior && w.match_type_prior === "fuzzy") ? '<span class="fuzz" title="approximate prior (boundary change)">≈</span>' : "";
      const priorPill = w.prior_party
        ? `<span class="winpill" style="background:${priorColor}">${partyShort[w.prior_party] || w.prior_party}</span>`
        : `<span class="winpill" style="background:#b6ad9c;color:#2a2620">none</span>`;
      const newPill = w.winner
        ? `<span class="winpill" style="background:${newColor}">${partyShort[w.winner] || w.winner}</span>`
        : `<span class="winpill" style="background:${partyColors.Pending}">Pending</span>`;
      let statusPill;
      if (w.flipped === true)       statusPill = '<span class="flip-pill flip">flip</span>';
      else if (w.flipped === false) statusPill = '<span class="flip-pill hold">hold</span>';
      else                          statusPill = '<span class="flip-pill np">n/a</span>';
      row.innerHTML = `
        <span class="name">${w.ward}${fuzz}</span>
        ${priorPill}
        ${newPill}
        ${statusPill}
        <span class="num col-hide-mobile">${dens}</span>
        <span class="num col-hide-mobile">${l4}</span>
        <span class="num col-hide-mobile">${uk}</span>
      `;
      block.appendChild(row);
    });
    flippedList.appendChild(block);
  });
}
''')

    new_js = '\n'.join(js_lines)

    html_path = DOCS / 'changes.html'
    html = html_path.read_text()
    pattern = re.compile(re.escape(BEGIN) + r'\n.*?\n' + re.escape(END), re.DOTALL)
    matches = pattern.findall(html)
    if len(matches) != 1:
        raise SystemExit(
            f'Expected exactly one BEGIN/END pair in {html_path}, found {len(matches)}.'
        )
    new_html = pattern.sub(lambda _m: BEGIN + '\n' + new_js + '\n' + END, html, count=1)
    html_path.write_text(new_html)

    print(f'Spliced {len(new_js)} chars of generated JS into {html_path.relative_to(ROOT)}')
    print(f'  RAW entries: {len(raw)}')
    print(f'  corrData variables: {len(corrData)}')
    print(f'  flip parties (sorted by n_flipped desc): {flip_parties}')


if __name__ == '__main__':
    main()
