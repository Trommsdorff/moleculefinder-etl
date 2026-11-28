"""One weight formatter (trust 3C, 2026-11-27): half up, never more precision than the record, one function."""
import json
import re
from pathlib import Path

import pytest

from moleculefinder_etl.transform import assemble
from moleculefinder_etl.transform.weights import (
    WHOLE,
    description_places,
    format_weight,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests" / "data" / "weight_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c['value']}@{c['decimals']}")
def test_the_shared_cases(case):
    assert format_weight(case["value"], case["decimals"]) == case["shown"]


def test_half_up_never_half_even_and_never_added_precision():
    assert [format_weight(w, WHOLE) for w in (360.5, 406.5, 362.5, 374.5, 580.5, 286.5, 434.5)] == \
        ["361", "407", "363", "375", "581", "287", "435"]
    assert format_weight(271.4, 2) == "271.4"          # never 271.40
    assert format_weight(5808.0) == "5,808"


def test_the_description_prints_the_weight_through_it():
    rec = {"title": "Retinol", "molecular_formula": "C20H30O", "molecular_weight": 286.5,
           "scope_family": "vitamin", "scope_bucket": "nutrient-vitamin"}
    assert "(C20H30O, 287 g/mol)" in assemble._identity_clause(rec)
    assert description_places(4.0026) == 1 and format_weight(4.0026, description_places(4.0026)) == "4"


def test_no_other_etl_code_formats_a_weight():
    """A weight is formatted only by transform/weights.py: no round(), f-string format spec or _fmt_num on a
    molecular weight anywhere else in the package."""
    bad = []
    for p in (ROOT / "moleculefinder_etl").rglob("*.py"):
        if p.name == "weights.py":
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if re.search(r"(round\(|_fmt_num\(|:[,.]\d*f?\}|:,\})[^\n]*\b(mw|molecular_weight)\b|\b(mw|molecular_weight)\b[^\n]*(round\(|_fmt_num\(|:[,.]\d*f?\}|:,\})", line) \
                    and "format_weight" not in line:
                bad.append(f"{p.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not bad, "a weight formatted outside transform/weights.py:\n" + "\n".join(bad)
