"""Load and query the master council registry from data/source/councils.yaml.

The registry is the single source of truth for which councils exist, which
region(s) each belongs to, and where to find their Wikipedia results articles.
Used by the fetch scripts (00, 00b) and the GSS-matching step (02), and by
the renderers (07/07b/07c) to resolve a --region argument to a set of
LAD24 codes.
"""
import functools
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COUNCILS_PATH = ROOT / "data" / "source" / "councils.yaml"


@functools.lru_cache(maxsize=1)
def load() -> list[dict]:
    """Return the full registry as a list of dicts in YAML order."""
    with open(COUNCILS_PATH) as f:
        return yaml.safe_load(f)


def for_region(region: str) -> list[dict]:
    """Return the council rows belonging to the given region, in YAML order.

    Known regions:
      'gm' — Greater Manchester (entries with region_gm: true)
      'gb' — Great Britain (every entry)
    """
    if region == "gb":
        return list(load())
    if region == "gm":
        return [c for c in load() if c.get("region_gm")]
    raise ValueError(f"Unknown region: {region!r}. Known: 'gm', 'gb'.")


def lad_codes_for(region: str) -> set[str]:
    """Return the set of LAD24 codes belonging to the given region."""
    return {c["lad_code"] for c in for_region(region)}
