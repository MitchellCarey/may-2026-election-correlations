"""Generate the parallel-coordinates SVG (party-win × Census r) and
splice it into the matching index page between the BEGIN/END SVG markers.

Reads:  data/correlations.json
Writes: docs/index.html       (when --region=gm)
        docs/uk/index.html    (when --region=gb)

The chart shows Pearson r between a 0/1 party-win indicator and ten
ward-level structural variables across the region's declared wards.
We emit one SVG per sortable party — each with its own variable order,
subtitle, and annotations. The default-visible SVG is Reform's; the
others are hidden until a button in the host HTML flips visibility.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

REGION_NAME = {"gm": "Greater Manchester", "gb": "Great Britain"}

ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
ap.add_argument("--region", default="gm", choices=["gm", "gb"])
args = ap.parse_args()
region = args.region
region_name = REGION_NAME[region]

with open(DATA / "correlations.json") as f:
    _corr_full = json.load(f)
corr = _corr_full["regions"][region]["correlations"]
n_total = _corr_full["regions"][region]["n_total"]

# Pool of structural variables available to the chart. Each party-view
# picks its own top-10 by |r| from this pool, ordered most-positive →
# most-negative. The pool matches the 17 numeric vars in
# correlations.json (everything except n_wards).
VAR_LABELS = {
    "density":            "Pop. density",
    "median_age":         "Median age",
    "pct_under18":        "% Aged 0–17",
    "pct_18_29":          "% Aged 18–29",
    "pct_30_49":          "% Aged 30–49",
    "pct_50_64":          "% Aged 50–64",
    "pct_65plus":         "% Aged 65+",
    "pct_apprentice":     "% Apprenticeship",
    "pct_level4_plus":    "% Degree (L4+)",
    "pct_no_qual":        "% No qualifications",
    "pct_soc123":         "% SOC 1–3",
    "pct_owned":          "% Owner-occupied",
    "pct_social_rented":  "% Social rented",
    "pct_private_rented": "% Private rented",
    "pct_uk_born":        "% UK-born",
    "pct_wfh":            "% WFH",
    "pct_female":         "% Female",
}

# Number of variables shown per chart. Fixed across views so the chart's
# width and column count don't shift between party selections.
N_VARS = 10

# (key, color, stroke px, n)
PARTIES = [
    ("Reform",       "#00b8c4", 3.5, corr["Reform"]["n_wards"]),
    ("Green",        "#2c8c4f", 3.5, corr["Green"]["n_wards"]),
    ("Labour",       "#c8362a", 2.0, corr["Labour"]["n_wards"]),
    ("LibDem",       "#e6a228", 2.0, corr["LibDem"]["n_wards"]),
    ("Conservative", "#1d4f8a", 2.0, corr["Conservative"]["n_wards"]),
]

# Parties available as the "sort anchor" (button targets), in display order.
SORT_PARTIES = ["Reform", "Green", "Labour", "LibDem", "Conservative"]
DEFAULT_SORT = "Reform"

# Subtitle uses a friendly display name.
DISPLAY_NAME = {
    "Reform": "Reform",
    "Green": "Green",
    "Labour": "Labour",
    "LibDem": "Lib Dem",
    "Conservative": "Conservative",
}

# Geometry
W, H = 720, 480
PL, PR = 60, 700        # plot left / right
PT, PB = 130, 360       # plot top / bottom
PLOT_W = PR - PL
PLOT_H = PB - PT
N = N_VARS

# Y axis is fixed at [-0.7, +0.7] — non-negotiable; auto-scaling would
# make Labour's near-zero line look meaningfully off-axis.
Y_MIN, Y_MAX = -0.7, 0.7


def xpos(i):
    # Inset the column positions a touch from the plot edges so the
    # leftmost and rightmost dots aren't flush with the Y axis / chart edge.
    return PL + 22 + i * ((PLOT_W - 44) / (N - 1))


def ypos(r):
    return PB - ((r - Y_MIN) / (Y_MAX - Y_MIN)) * PLOT_H


def fmt_r(r):
    rr = round(r, 2)
    if rr > 0:
        return f"+{rr:.2f}"
    if rr < 0:
        return f"−{abs(rr):.2f}"  # U+2212 minus
    return "0.00"


def top_vars_for(party):
    """Return [(key, label), ...] of the party's top-N by |r|, sorted by
    signed r descending (most positive → most negative)."""
    scored = [(k, corr[party][k]) for k in VAR_LABELS if k in corr[party]]
    top = sorted(scored, key=lambda kv: -abs(kv[1]))[:N_VARS]
    top.sort(key=lambda kv: -kv[1])
    return [(k, VAR_LABELS[k]) for k, _ in top]


def annotations_for(sort_party, var_order):
    """Annotate the sort party's leftmost (most positive) and rightmost
    (most negative) dots — same rule for every view."""
    leftmost_var = var_order[0][0]
    rightmost_var = var_order[-1][0]
    left_r = corr[sort_party][leftmost_var]
    right_r = corr[sort_party][rightmost_var]
    left_dy = -8 if left_r >= 0 else 16
    right_dy = -8 if right_r >= 0 else 16
    return [
        (sort_party, leftmost_var,  fmt_r(left_r),   9, left_dy,  "start"),
        (sort_party, rightmost_var, fmt_r(right_r), -9, right_dy, "end"),
    ]


def build_svg(sort_party, is_default):
    """Build one SVG showing this party's top-N most-correlated variables,
    ordered most-positive → most-negative by signed r."""
    var_order = top_vars_for(sort_party)

    s = []
    visibility_class = "parallel-svg is-visible" if is_default else "parallel-svg"
    s.append(
        f'<svg class="{visibility_class}" data-sort="{sort_party}" '
        f'viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Parallel-coordinates chart of party-win '
        f'correlations with structural variables across {n_total} {region_name} '
        f'wards, ordered by {DISPLAY_NAME[sort_party]}\'s correlation strength" '
        f'style="width:100%;height:auto;">'
    )
    # Background card
    s.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fafaf7"/>')

    # Title — accessible serif, dark ink
    s.append(
        f'<text x="{PL}" y="24" font-family="\'Source Serif 4\', Georgia, serif" '
        f'font-size="18" font-weight="700" fill="#14110d">'
        f'Where each party wins, structurally — {region_name} 2026 wards</text>'
    )

    # Subtitle — Inter Tight, three lines so it doesn't collide with the legend
    sub_lines = [
        "Pearson r between a 0/1 party-win indicator and each ward's Census",
        f"2021 structural profile, across {n_total} declared wards. Showing the ten",
        f"variables most correlated with {DISPLAY_NAME[sort_party]}'s wins.",
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
    draw_order = list(reversed(PARTIES))
    for party_key, color, stroke, _n in draw_order:
        pts = [(xpos(i), ypos(corr[party_key][var])) for i, (var, _) in enumerate(var_order)]
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
    # down directly under its column.
    for i, (_var, label) in enumerate(var_order):
        x = xpos(i)
        y = PB + 8
        s.append(
            f'<g transform="translate({x:.1f} {y}) rotate(-90)">'
            f'<text x="0" y="3" text-anchor="end" '
            f'font-family="\'Atkinson Hyperlegible\', sans-serif" '
            f'font-size="10.5" fill="#14110d">{label}</text>'
            f'</g>'
        )

    # Annotations — hand-tuned for Reform, auto for the others.
    var_idx = {var: i for i, (var, _) in enumerate(var_order)}
    party_color = {p[0]: p[1] for p in PARTIES}
    for party_key, var, label, dx, dy, anchor in annotations_for(sort_party, var_order):
        i = var_idx[var]
        x = xpos(i) + dx
        y = ypos(corr[party_key][var]) + dy
        s.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-family="\'JetBrains Mono\', monospace" font-size="10.5" '
            f'font-weight="700" fill="{party_color[party_key]}">{label}</text>'
        )

    s.append('</svg>')
    return "\n".join(s)


# Build one SVG per sort-anchor party.
svgs = [build_svg(p, is_default=(p == DEFAULT_SORT)) for p in SORT_PARTIES]
new_block = "\n".join(svgs)

# Splice into the region's host HTML
BEGIN = "<!-- ===== BEGIN GENERATED SVG — see scripts/08_parallel_chart.py ===== -->"
END = "<!-- ===== END GENERATED SVG ===== -->"
html_path = DOCS / "index.html" if region == "gm" else DOCS / "uk" / "index.html"
html = html_path.read_text()
pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
matches = pattern.findall(html)
if len(matches) != 1:
    raise SystemExit(
        f"Expected exactly one BEGIN/END SVG marker pair in {html_path}, "
        f"found {len(matches)}. Add the markers around the chart container "
        f"in docs/index.html before re-running."
    )
new_html = pattern.sub(lambda _m: BEGIN + "\n" + new_block + "\n" + END, html, count=1)
html_path.write_text(new_html)

print(
    f"Spliced {len(new_block)} chars of SVG into "
    f"{html_path.relative_to(ROOT)} "
    f"({len(SORT_PARTIES)} sort variants × {N} variables × {len(PARTIES)} parties)"
)
