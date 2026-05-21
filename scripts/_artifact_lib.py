"""Shared constants and JS-fragment generators for scripts/07*.py.

Centralises the party palette, Census-variable labels, and ordering used by
the Winners (07), Changes (07b), and Map (07c) builders so a render-layer
change lands once. The JS-emit functions return strings sized to splice
in byte-identical to the previously inline JS-literal blocks in each script.
"""


CORR_LABELS = {
    "density":            "Population density (per km²)",
    "median_age":         "Median age (years)",
    "mean_income":        "Net household income (£/yr, before housing)",
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
    "SNP":          "#FDF38E",
    "Plaid":        "#005B54",
    "Independent":  "#888780",
    # The Speaker of the House contests as "Speaker" rather than a party
    # (Lindsay Hoyle, Chorley). Same grey as Independent so the map reads
    # "non-party" at a glance.
    "Speaker":      "#888780",
    # EP 2014/2019 (issue #91). UKIP brand purple (their 1993-2019 livery)
    # and Brexit Party brand light-blue (2019 EP campaign). Reform UK
    # legally inherited the Brexit Party registration after 2020 but uses
    # a brighter cyan (#12B6CF above) — keeping Brexit's lighter blue
    # distinct so a reader scanning 2019 vs 2024 sees the two as different
    # layers even though the legal entity is the same.
    "UKIP":         "#70147A",
    "Brexit":       "#00AEEF",
    # Referendum outcomes (issue #85) — Leave/Remain are stored as the
    # `w` field on EU-ref records so the same PARTY_COLOURS lookup that
    # paints party-winner polygons also paints referendum-winner polygons.
    # Purple recalls the UKIP brand that drove the Leave campaign; yellow
    # recalls the stars on the EU flag. Same swatch is reused by #86's
    # Yes/No (Scottish indyref 2014) when that ships.
    "Leave":        "#552288",
    "Remain":       "#ffcc00",
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
    "SNP":          "SNP",
    "Plaid":        "Plaid Cymru",
    "Independent":  "Independent",
    "Speaker":      "Speaker of the House",
    "UKIP":         "UKIP",
    "Brexit":       "Brexit Party",
    "Leave":        "Leave",
    "Remain":       "Remain",
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
    "SNP", "Plaid", "Independent", "Speaker",
    # EP 2014/2019 (issue #91) — only present in the GB Current map's
    # European Parliament view (and chronologically beneath other layers
    # in the default view). Ordered after the SNP/Plaid devolved parties
    # but before Independent/Speaker so the legend reads from largest GB
    # vote share downward.
    "UKIP", "Brexit",
    # Referendum outcomes (issue #85) — only present in the GB Current
    # map and only when the EU Ref 2016 view is active. The labels still
    # ship in the shared legend so the swatch-to-meaning mapping is
    # available; the EU-ref view's CSS leaves the legend visible.
    "Leave", "Remain",
    "Other", "Pending",
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
