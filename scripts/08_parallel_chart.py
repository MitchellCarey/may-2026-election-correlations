"""Generate the parallel-coordinates SVG (party-win × Census r) and
splice it into docs/index.html between the BEGIN/END SVG markers.

Reads:  data/gm_correlations.json
Writes: docs/index.html (SVG block only, between marker pair)

The chart shows Pearson r between a 0/1 party-win indicator and ten
ward-level structural variables across the 213 declared GM wards. The
ten variables are listed left-to-right in descending order of Reform's
correlation, so Reform's line slopes from upper-left to lower-right by
construction; the Green line's near-perfect inversion is the headline.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

with open(DATA / "gm_correlations.json") as f:
    corr = json.load(f)["correlations"]

# Variable order: by Reform's r, most positive → most negative.
# (key, x-axis label)
VAR_ORDER = [
    ("pct_apprentice",     "% Apprenticeship"),
    ("pct_uk_born",        "% UK-born"),
    ("pct_50_64",          "% Aged 50–64"),
    ("pct_65plus",         "% Aged 65+"),
    ("pct_owned",          "% Owner-occupied"),
    ("pct_18_29",          "% Aged 18–29"),
    ("pct_private_rented", "% Private rented"),
    ("density",            "Pop. density"),
    ("pct_soc123",         "% SOC 1–3"),
    ("pct_level4_plus",    "% Degree (L4+)"),
]

# (key, color, stroke px, n)
PARTIES = [
    ("Reform",       "#00b8c4", 3.5, corr["Reform"]["n_wards"]),
    ("Green",        "#2c8c4f", 3.5, corr["Green"]["n_wards"]),
    ("Labour",       "#c8362a", 2.0, corr["Labour"]["n_wards"]),
    ("LibDem",       "#e6a228", 2.0, corr["LibDem"]["n_wards"]),
    ("Conservative", "#1d4f8a", 2.0, corr["Conservative"]["n_wards"]),
]

# Geometry
W, H = 720, 480
PL, PR = 60, 700        # plot left / right
PT, PB = 130, 360       # plot top / bottom
PLOT_W = PR - PL
PLOT_H = PB - PT
N = len(VAR_ORDER)

# Y axis is fixed at [-0.7, +0.7] — non-negotiable; auto-scaling would
# make Labour's near-zero line look meaningfully off-axis.
Y_MIN, Y_MAX = -0.7, 0.7

# Inset the column positions a touch from the plot edges so the leftmost
# and rightmost dots aren't flush with the Y axis / chart edge.
def xpos(i):
    return PL + 22 + i * ((PLOT_W - 44) / (N - 1))

def ypos(r):
    return PB - ((r - Y_MIN) / (Y_MAX - Y_MIN)) * PLOT_H


s = []
s.append(
    f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
    f'role="img" aria-label="Parallel-coordinates chart of party-win '
    f'correlations with structural variables across 213 Greater Manchester '
    f'wards" style="width:100%;height:auto;display:block;">'
)
# Background card
s.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fafaf7"/>')

# Title — accessible serif, dark ink
s.append(
    f'<text x="{PL}" y="24" font-family="\'Source Serif 4\', Georgia, serif" '
    f'font-size="18" font-weight="700" fill="#14110d">'
    f'Where each party wins, structurally — Greater Manchester 2026 wards</text>'
)

# Subtitle — Inter Tight, three lines so it doesn't collide with the legend
sub_lines = [
    "Pearson r between a 0/1 party-win indicator and each ward's Census",
    "2021 structural profile, across 213 declared wards. Variables ordered",
    "by Reform's correlation strength.",
]
for i, line in enumerate(sub_lines):
    s.append(
        f'<text x="{PL}" y="{48 + i*14}" '
        f'font-family="\'Inter Tight\', \'Atkinson Hyperlegible\', sans-serif" '
        f'font-size="11" fill="#6b6256">{line}</text>'
    )

# Legend right-side, sitting below the title and beside the subtitle
LEG_X = 480
LEG_Y0 = 60
s.append(
    f'<text x="{LEG_X}" y="{LEG_Y0 - 14}" '
    f'font-family="\'JetBrains Mono\', monospace" font-size="9" '
    f'font-weight="700" fill="#6b6256" letter-spacing="0.10em">'
    f'PARTY · WARDS WON</text>'
)
for k, (party_key, color, stroke, n) in enumerate(PARTIES):
    y = LEG_Y0 + k * 14
    # short stroke + center dot, matching the chart line/dot rendering
    s.append(
        f'<line x1="{LEG_X}" y1="{y - 3}" x2="{LEG_X + 26}" y2="{y - 3}" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round"/>'
    )
    s.append(
        f'<circle cx="{LEG_X + 13}" cy="{y - 3}" r="3.2" fill="{color}"/>'
    )
    s.append(
        f'<text x="{LEG_X + 34}" y="{y}" '
        f'font-family="\'Atkinson Hyperlegible\', sans-serif" '
        f'font-size="11" font-weight="600" fill="#14110d">{party_key}</text>'
    )
    s.append(
        f'<text x="{LEG_X + 222}" y="{y}" text-anchor="end" '
        f'font-family="\'JetBrains Mono\', monospace" font-size="10.5" '
        f'fill="#6b6256">n={n}</text>'
    )

# Vertical column gridlines (one per variable)
for i in range(N):
    x = xpos(i)
    s.append(
        f'<line x1="{x:.1f}" y1="{PT}" x2="{x:.1f}" y2="{PB}" '
        f'stroke="rgba(20,17,13,0.10)" stroke-width="0.7"/>'
    )

# Horizontal Y-axis ticks at -0.6, -0.3, 0, +0.3, +0.6
yticks = [-0.6, -0.3, 0.0, 0.3, 0.6]
for r in yticks:
    y = ypos(r)
    is_zero = (r == 0.0)
    width = 1.6 if is_zero else 0.7
    color = "rgba(20,17,13,0.55)" if is_zero else "rgba(20,17,13,0.16)"
    s.append(
        f'<line x1="{PL}" y1="{y:.1f}" x2="{PR}" y2="{y:.1f}" '
        f'stroke="{color}" stroke-width="{width}"/>'
    )
    if r > 0:
        label = f"+{r:.1f}"
    elif r < 0:
        label = f"−{abs(r):.1f}"  # U+2212 minus
    else:
        label = "0"
    s.append(
        f'<text x="{PL - 8}" y="{y + 3.5:.1f}" text-anchor="end" '
        f'font-family="\'JetBrains Mono\', monospace" font-size="10" '
        f'fill="#6b6256">{label}</text>'
    )

# Y-axis line on the left
s.append(
    f'<line x1="{PL}" y1="{PT}" x2="{PL}" y2="{PB}" '
    f'stroke="rgba(20,17,13,0.55)" stroke-width="1"/>'
)

# Lines (path) and dots, drawn back to front: weaker parties first so
# Reform and Green sit on top.
draw_order = list(reversed(PARTIES))  # Conservative → LibDem → Labour → Green → Reform
for party_key, color, stroke, _n in draw_order:
    pts = [(xpos(i), ypos(corr[party_key][var])) for i, (var, _) in enumerate(VAR_ORDER)]
    path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    s.append(
        f'<path d="{path}" fill="none" stroke="{color}" '
        f'stroke-width="{stroke}" stroke-linejoin="round" '
        f'stroke-linecap="round" opacity="0.95"/>'
    )
    for x, y in pts:
        s.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" '
            f'fill="{color}" stroke="#fafaf7" stroke-width="1"/>'
        )

# X-axis labels — vertical (rotate -90), each label hanging straight
# down directly under its column. text-anchor="end" + rotate(-90) puts
# the right end of the text at the tick (top) and the rest of the label
# below, so labels read bottom-up.
for i, (_var, label) in enumerate(VAR_ORDER):
    x = xpos(i)
    y = PB + 8
    s.append(
        f'<g transform="translate({x:.1f} {y}) rotate(-90)">'
        f'<text x="0" y="3" text-anchor="end" '
        f'font-family="\'Atkinson Hyperlegible\', sans-serif" '
        f'font-size="10.5" fill="#14110d">{label}</text>'
        f'</g>'
    )

# Annotations: r values on the four extreme dots that carry the story.
# (party_key, var_key, label, dx, dy, anchor)
ANNOTS = [
    ("Reform", "pct_apprentice",     "+0.64", 9,  -8,  "start"),
    ("Green",  "pct_apprentice",     "−0.59", 9,  16,  "start"),
    ("Reform", "pct_level4_plus",    "−0.50", -9, 16,  "end"),
    ("Green",  "pct_private_rented", "+0.62", -9, -8,  "end"),
]
var_idx = {var: i for i, (var, _) in enumerate(VAR_ORDER)}
party_color = {p[0]: p[1] for p in PARTIES}
for party_key, var, label, dx, dy, anchor in ANNOTS:
    i = var_idx[var]
    x = xpos(i) + dx
    y = ypos(corr[party_key][var]) + dy
    s.append(
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'font-family="\'JetBrains Mono\', monospace" font-size="10.5" '
        f'font-weight="700" fill="{party_color[party_key]}">{label}</text>'
    )

s.append('</svg>')
new_svg = "\n".join(s)

# Splice into docs/index.html
BEGIN = "<!-- ===== BEGIN GENERATED SVG — see scripts/08_parallel_chart.py ===== -->"
END = "<!-- ===== END GENERATED SVG ===== -->"
html_path = DOCS / "index.html"
html = html_path.read_text()
pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
matches = pattern.findall(html)
if len(matches) != 1:
    raise SystemExit(
        f"Expected exactly one BEGIN/END SVG marker pair in {html_path}, "
        f"found {len(matches)}. Add the markers around the chart container "
        f"in docs/index.html before re-running."
    )
new_html = pattern.sub(lambda _m: BEGIN + "\n" + new_svg + "\n" + END, html, count=1)
html_path.write_text(new_html)

print(
    f"Spliced {len(new_svg)} chars of SVG into "
    f"{html_path.relative_to(ROOT)} ({N} variables × {len(PARTIES)} parties)"
)
