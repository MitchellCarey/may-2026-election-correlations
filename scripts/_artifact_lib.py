"""Shared constants and JS-fragment generators for scripts/07*.py.

Centralises the party palette, Census-variable labels, and ordering used by
the Winners (07), Changes (07b), and Map (07c) builders so a render-layer
change lands once. The JS-emit functions return strings sized to splice
in byte-identical to the previously inline JS-literal blocks in each script.
"""


CORR_LABELS = {
    "density":            "Population density (per km²)",
    "median_age":         "Median age (years)",
    "pct_under18":        "% aged under 18",
    "pct_18_29":          "% aged 18-29",
    "pct_30_49":          "% aged 30-49",
    "pct_50_64":          "% aged 50-64",
    "pct_65plus":         "% aged 65+",
    "pct_apprentice":     "% with apprenticeship",
    "pct_level4_plus":    "% with Level 4+ (degree)",
    "pct_soc123":         "% in SOC 1-3 (graduate-level jobs)",
    "pct_no_qual":        "% with no qualifications",
    "pct_uk_born":        "% born in UK",
    "pct_private_rented": "% Private rent",
    "pct_social_rented":  "% Social housing",
    "pct_owned":          "% Owned",
    "pct_wfh":            "% Working from home",
    "pct_female":         "% Female",
    "pct_white":          "% White",
    "pct_asian":          "% Asian / Asian British",
    "pct_black":          "% Black / Black British",
    "pct_mixed":          "% Mixed / Multiple ethnicity",
    "pct_other_ethnic":   "% Other ethnic group",
}

# CSS-variable palette used by the Winners and Changes pages. Hex fallbacks
# (Conservative/Independent/Other/Pending) cover parties without a CSS var.
PARTY_COLOURS_TEXT = {
    "Green":        "var(--green)",
    "Reform":       "var(--reform)",
    "Labour":       "var(--labour)",
    "LibDem":       "var(--libdem)",
    "Conservative": "#1d4f8a",
    "Independent":  "#888",
    "Other":        "#a87b3e",
    "Pending":      "#bbb",
}

# Vivid hex palette used by the Map page. Tuned for legibility on small
# polygons; the CSS-variable palette above washes out at choropleth fill scale.
PARTY_COLOURS_MAP = {
    "Labour":       "#c8102e",
    "Conservative": "#0087DC",
    "LibDem":       "#FAA61A",
    "Reform":       "#12B6CF",
    "Green":        "#6AB023",
    "Independent":  "#888780",
    "Other":        "#a87b3e",
    "Pending":      "#cccccc",
}

# Shared by Winners and Changes; the "Other" entry differs between them
# and is supplied per page via party_display_text_js(other_label=...).
_PARTY_DISPLAY_TEXT_BASE = {
    "Green":        "Greens",
    "Labour":       "Labour",
    "Reform":       "Reform UK",
    "LibDem":       "Liberal Democrats",
    "Conservative": "Conservatives",
    "Independent":  "Independent / local",
    "Other":        "Other",
    "Pending":      "Awaiting declaration",
}

PARTY_DISPLAY_MAP = {
    "Labour":       "Labour",
    "Conservative": "Conservative",
    "LibDem":       "Liberal Democrats",
    "Reform":       "Reform UK",
    "Green":        "Green",
    "Independent":  "Independent",
    "Other":        "Other",
    "Pending":      "Awaiting declaration",
}

PARTY_SHORT = {
    "Green":        "Green",
    "Labour":       "Labour",
    "Reform":       "Reform",
    "LibDem":       "LibDem",
    "Conservative": "Cons",
    "Independent":  "Indep",
    "Other":        "Other",
    "Pending":      "Pending",
}

PARTY_ORDER_WINNERS = [
    "Reform", "Green", "Labour", "LibDem", "Conservative",
    "Independent", "Other", "Pending",
]

LEGEND_ORDER_MAP = [
    "Labour", "Reform", "Green", "LibDem", "Conservative",
    "Independent", "Other", "Pending",
]


def corr_labels_js_quoted_keys() -> str:
    """`const corrLabels = { "key": "value", ... };` — Winners style."""
    lines = ["const corrLabels = {"]
    for k, v in CORR_LABELS.items():
        lines.append(f'  "{k}": "{v}",')
    lines.append("};")
    return "\n".join(lines)


def corr_labels_js_unquoted_keys() -> str:
    """`const corrLabels = { key: "value", ... };` — Changes style."""
    lines = ["const corrLabels = {"]
    for k, v in CORR_LABELS.items():
        lines.append(f'  {k}: "{v}",')
    lines.append("};")
    return "\n".join(lines)


def party_colours_text_js() -> str:
    body = ",\n".join(f'  {k}: "{v}"' for k, v in PARTY_COLOURS_TEXT.items())
    return f"const partyColors = {{\n{body}\n}};"


def party_display_text_js(*, other_label: str) -> str:
    display = {**_PARTY_DISPLAY_TEXT_BASE, "Other": other_label}
    body = ",\n".join(f'  {k}: "{v}"' for k, v in display.items())
    return f"const partyDisplay = {{\n{body}\n}};"


def party_short_js() -> str:
    body = ",\n".join(f'  {k}: "{v}"' for k, v in PARTY_SHORT.items())
    return f"const partyShort = {{\n{body}\n}};"


def party_order_winners_js() -> str:
    items = ",".join(f'"{p}"' for p in PARTY_ORDER_WINNERS)
    return f"const partyOrder = [{items}];"
