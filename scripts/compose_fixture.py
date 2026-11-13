#!/usr/bin/env python3
"""Write the web's proof fixture for the drawing layers (phase 5B, 2026-11-12).

The web composes a part or pair layer under a drawing with its own copy of `drawings.compose` (and of the pair
`frame`), lib/drawings.ts. This writes, from the committed snapshot, the sha256 of the ETL's own composition for
caffeine's three parts and for the caffeine and theobromine pair (both sides), so the web test can prove its
composition is byte for byte the ETL's. Run after `mfetl all`:

    ./.venv/bin/python3 scripts/compose_fixture.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moleculefinder_etl.transform import drawings as D

SNAP = ROOT / "data" / "snapshots"
OUT = ROOT.parent / "moleculefinder-web" / "lib" / "fixtures" / "drawings-compose.json"


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main() -> None:
    caf = json.loads((SNAP / "molecules" / "caffeine.json").read_text())
    pair = json.loads((SNAP / "compare_drawings.json").read_text())["pairs"]["caffeine-vs-theobromine"]
    a = D.compose(caf["structure_svg"], pair["a_layer"])
    if pair.get("frame"):
        a = D._with_frame(a, pair["frame"])
    out = {
        "//": "The ETL's own composition (drawings.compose), as sha256, written by moleculefinder-etl/scripts/"
              "compose_fixture.py from the committed snapshot; lib/drawings.test.ts holds lib/drawings.ts to it.",
        "parts": {p["id"]: sha(D.compose(caf["structure_svg"], p["layer"]))
                  for p in caf["structure_parts"]["parts"]},
        "pair": {"slug": "caffeine-vs-theobromine", "a": sha(a), "b": sha(D.compose(pair["b_svg"], pair["b_layer"]))},
    }
    # one pair whose second drawing outgrows 400 by 300, so the shared `frame` is proven too
    pairs = json.loads((SNAP / "compare_drawings.json").read_text())["pairs"]
    slug, fr = next((k, v) for k, v in sorted(pairs.items()) if v.get("frame") and v.get("highlight"))
    first = json.loads((SNAP / "molecules" / f"{fr['a']}.json").read_text())
    out["framed"] = {"slug": slug, "a": sha(D._with_frame(D.compose(first["structure_svg"], fr["a_layer"]), fr["frame"]))}
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
