"""Plurality-party winner picker for multi-seat ward results.

Bespoke parsers collect every "Elected" row in a ward block and pass them
to pick_plurality to choose the single record written to
ward_official_<year>.csv. The map paints one party per ward, so the right
semantic is plurality (party with the most elected seats), with ties on
seat count broken by the highest-vote elected row across the tied parties.

For single-seat wards there's one elected row and this is a pass-through;
for multi-seat wards with a uniform slate (e.g. Salford Cadishead and
Lower Irlam — 2 Reform UK) the chosen party also doesn't change. The
behaviour only differs from "first listed elected" when the slate is
split AND the source orders rows by something other than vote rank (e.g.
Swindon's alphabetical-by-surname tables) — or when the slate is split
and the top-of-poll candidate's party didn't win the plurality (real in
some ModernGov London-borough wards).
"""
from collections import Counter

from _wiki_parser import normalize_party


def pick_plurality(rows: list[tuple[str, str, int]]) -> tuple[str, str, int] | None:
    """rows: [(party_raw, candidate, votes), ...] for every elected row in
    a ward. Returns the row whose normalised party won the most seats,
    breaking ties by highest votes. Empty input → None."""
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    seat_counts = Counter(normalize_party(party) for party, _, _ in rows)
    top_count = max(seat_counts.values())
    leading = {p for p, c in seat_counts.items() if c == top_count}
    return max(
        (r for r in rows if normalize_party(r[0]) in leading),
        key=lambda r: r[2],
    )
