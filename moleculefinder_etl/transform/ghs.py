"""Parse a PubChem PUG-View 'GHS Classification' record.

Pulls the three things a hazard chip needs: the signal word (most severe wins),
the H-statement codes, and the GHS pictogram codes. Pictograms are not in the
text leaves — PubChem carries them as pictogram image URLs in `Markup` nodes
(e.g. ``.../images/ghs/GHS07.svg``), so we walk those separately.
"""
from __future__ import annotations
import re
from .confidence import label_for
from .toxicity import _iter_strings

_SIGNAL = re.compile(r"\b(Danger|Warning)\b")
_HCODE = re.compile(r"\bH\d{3}\b")
_PICTO = re.compile(r"GHS0\d")


def _iter_markup_urls(node):
    """Yield every Markup URL in a PUG-View tree (where pictogram icons live)."""
    if isinstance(node, dict):
        for m in node.get("Markup", []) or []:
            if isinstance(m, dict) and m.get("URL"):
                yield m["URL"]
        for v in node.values():
            yield from _iter_markup_urls(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_markup_urls(v)


def parse_ghs(pug_view: dict | None) -> dict | None:
    if not pug_view:
        return None
    signals, hcodes, pictos = set(), set(), set()
    for text in _iter_strings(pug_view):
        signals.update(_SIGNAL.findall(text))
        hcodes.update(_HCODE.findall(text))
    for url in _iter_markup_urls(pug_view):
        pictos.update(_PICTO.findall(url))
    if not (signals or hcodes):
        return None
    # GHS uses the most severe applicable signal word.
    signal = "Danger" if "Danger" in signals else ("Warning" if "Warning" in signals else None)
    return {"signal_word": signal, "pictograms": sorted(pictos),
            "h_statements": sorted(hcodes), "confidence": label_for("ghs")}
