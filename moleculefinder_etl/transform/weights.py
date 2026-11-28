"""One weight formatter (brief ../TRUST-3C-STATUS-AND-ROUNDING-PROMPT.md, part 2, 2026-11-27).

Every surface that prints a molecular weight prints it through ONE function: here in the ETL (the descriptions'
"(C20H30O, 287 g/mol)"), and its twin ``formatWeight`` in the web's ``scripts/weight-words.mjs`` for every page. Both
are tested against the same cases (``tests/data/weight_cases.json``, the web's copy must match it byte for byte).

THE RULE: a weight is printed at most to the precision asked for (``FULL``: the record's own; ``TWO``: two decimals;
``WHOLE``: whole grams), rounded HALF UP on the record's decimal value (286.5 is 287, never 286: Python's ``round`` is
half-even, which printed seven .5 weights rounded down), NEVER with more precision than the record holds (271.4 to two
decimals is 271.4, not 271.40; trailing zeros are dropped), with thousands grouped by commas (5,808).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

FULL: int | None = None
TWO = 2
WHOLE = 0


def format_weight(value: float, decimals: int | None = FULL) -> str:
    """'287' for (286.5, WHOLE); '271.4' for (271.4, TWO); '5,808' for (5808.0, FULL); '194.19' for (194.19, TWO)."""
    d = Decimal(repr(float(value)))
    if decimals is not None and -d.as_tuple().exponent > decimals:
        d = d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    whole, _, frac = text.partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = f"{int(whole.lstrip('-') or '0'):,}"
    return f"{sign}{whole}.{frac}" if frac else f"{sign}{whole}"


def description_places(value: float) -> int:
    """The descriptions' precision: whole grams from 10 g/mol up, one decimal below (helium is 4, lithium 6.9)."""
    return WHOLE if abs(value) >= 10 else 1
