"""The single labeling rule table: from_source / computed / inferred.

Every displayed value routes through here so the trust chip is consistent.
"""
from __future__ import annotations

FROM_SOURCE = "from_source"
COMPUTED = "computed"
INFERRED = "inferred"

# semantic category of a value -> confidence label
_RULES: dict[str, str] = {
    # raw fields lifted straight from a source
    "raw_field": FROM_SOURCE,
    "formula": FROM_SOURCE,
    "molecular_weight": FROM_SOURCE,
    "descriptor": FROM_SOURCE,
    "ld50_raw": FROM_SOURCE,
    "ghs": FROM_SOURCE,
    "relative_sweetness": FROM_SOURCE,
    "curated_fact": FROM_SOURCE,        # hand-authored, cites curator's source
    # things we calculate
    "scoville": COMPUTED,               # ppm -> SHU
    "similarity": COMPUTED,             # fingerprint Tanimoto
    "functional_group": COMPUTED,       # RDKit SMARTS substructure match
}


def label_for(kind: str) -> str:
    """Return the confidence label for a semantic value category."""
    try:
        return _RULES[kind]
    except KeyError as e:
        raise KeyError(f"No confidence rule for value kind '{kind}'. Add it to _RULES.") from e
