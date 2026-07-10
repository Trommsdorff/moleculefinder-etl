"""Choose a molecule's preferred/common display name."""
from __future__ import annotations


def preferred_name(cid: int, title: str | None, synonyms: list[str]) -> str:
    """Prefer the Wikidata label; fall back to the shortest non-systematic synonym."""
    if title:
        return title
    common = [s for s in synonyms if s and not s[0].isdigit() and len(s) < 40]
    return min(common, key=len) if common else f"CID {cid}"
