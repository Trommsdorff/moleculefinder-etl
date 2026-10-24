"""Parse a PubChem PUG-View 'GHS Classification' record.

Pulls the three things a hazard chip needs: the signal word (most severe wins),
the H-statement codes, and the GHS pictogram codes. Pictograms are not in the
text leaves — PubChem carries them as pictogram image URLs in `Markup` nodes
(e.g. ``.../images/ghs/GHS07.svg``), so we walk those separately.
"""
from __future__ import annotations
import re
from ..sources import registry
from .confidence import label_for
from .toxicity import _iter_information, _iter_strings

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


def parse_ghs(pug_view: dict | None, *, withheld: list | None = None) -> dict | None:
    """The hazard chip's signal word, H codes and pictograms, plus `sources` (registry keys).

    THE SOURCE-LICENCE RULE (2026-10-23): only Information items whose reference is a
    registered source that may be displayed contribute (`registry.may_display`); an
    unregistered source counts as not displayable. When `withheld` is a list, the name of each
    source whose items were left out is appended once, for the run log."""
    if not pug_view:
        return None
    rec = pug_view.get("Record", pug_view)
    names = {r.get("ReferenceNumber"): r.get("SourceName") for r in rec.get("Reference", []) or []}
    signals, hcodes, pictos, used, refused = set(), set(), set(), set(), set()
    for info in _iter_information(rec):
        source_name = names.get(info.get("ReferenceNumber"))
        key = registry.pugview_key(source_name)
        s_, h_, p_ = set(), set(), set()
        for text in _iter_strings(info):
            s_.update(_SIGNAL.findall(text))
            h_.update(_HCODE.findall(text))
        for url in _iter_markup_urls(info):
            p_.update(_PICTO.findall(url))
        if not (s_ or h_ or p_):
            continue
        if not registry.may_display(key):
            refused.add(source_name or "(no source named)")
            continue
        signals |= s_
        hcodes |= h_
        pictos |= p_
        used.add(key)
    if withheld is not None:
        withheld.extend(sorted(refused))
    if not (signals or hcodes):
        return None
    # GHS uses the most severe applicable signal word.
    signal = "Danger" if "Danger" in signals else ("Warning" if "Warning" in signals else None)
    return {"signal_word": signal, "pictograms": sorted(pictos),
            "h_statements": sorted(hcodes), "confidence": label_for("ghs"), "sources": sorted(used)}
