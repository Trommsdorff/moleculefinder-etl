#!/usr/bin/env python3
"""Fill the `pin: "?"` placeholders in the door seeds and what_it_does.yaml (phase 4, 2026-11).

A pin is the first 12 hex of sha256 over the quoted text, whitespace collapsed (transform/doors.pin).
This writes a pin ONLY where the seed says "?": it never overwrites an existing pin, because a pin that
no longer matches is the build telling a person to read the changed line again. After reading it,
replace that pin with "?" and run this to record the new one.

    ./.venv/bin/python3 scripts/door_pins.py            # fill every "?" from the committed snapshot
    ./.venv/bin/python3 scripts/door_pins.py --check    # list the placeholders, write nothing

It reads the committed snapshot (data/snapshots), so run it after `mfetl all`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moleculefinder_etl.transform import doors
from moleculefinder_etl.transform.relationships import load_worlds

SNAP = ROOT / "data" / "snapshots"
PLACEHOLDER = re.compile(r'pin: "\?"')


def catalog() -> doors._Catalog:
    mols = [json.loads(f.read_text()) for f in sorted((SNAP / "molecules").glob("*.json"))]
    cmp = json.loads((SNAP / "comparisons.json").read_text())
    prods = json.loads((SNAP / "products.json").read_text())["products"]
    pairs = json.loads((SNAP / "product_pairs.json").read_text())["pairs"]
    boards = {f.stem: json.loads(f.read_text()) for f in (SNAP / "leaderboards").glob("*.json") if f.stem != "index"}
    return doors._Catalog(mols, cmp, boards, prods, pairs, load_worlds())


def _find(node):
    """The mapping holding pin "?" inside a parsed line."""
    if isinstance(node, dict):
        if node.get("pin") == "?":
            return node
        for v in node.values():
            hit = _find(v)
            if hit is not None:
                return hit
    if isinstance(node, list):
        for v in node:
            hit = _find(v)
            if hit is not None:
                return hit
    return None


def _parse(line: str):
    return yaml.safe_load(line.strip().removeprefix("- "))


def fill(path: Path, cat: doors._Catalog, what_it_does: bool, check: bool) -> int:
    lines = path.read_text().splitlines(keepends=True)
    n = 0
    c = doors._Compiler(cat, path.stem)
    for i, line in enumerate(lines):
        if not PLACEHOLDER.search(line):
            continue
        ref = _find(_parse(line))
        if ref is None:
            raise SystemExit(f"{path.name}:{i + 1}: cannot read the reference on this line")
        if what_it_does:
            ref = {"sentence": ref["pair"], "starts": ref["starts"]}
        kind = next(k for k in doors.TEXT_KINDS if k in ref)
        text, _ = c._resolve_text(f"{path.name}:{i + 1}", kind, ref)
        if text is None:
            raise SystemExit("\n".join(c.problems))
        n += 1
        if check:
            print(f"{path.name}:{i + 1}: {doors.pin(text)}  {text}")
        else:
            lines[i] = PLACEHOLDER.sub(f'pin: "{doors.pin(text)}"', line, count=1)
    if not check and n:
        path.write_text("".join(lines))
    return n


def main() -> None:
    check = "--check" in sys.argv
    cat = catalog()
    total = sum(fill(f, cat, False, check) for f in sorted(doors.DOORS_DIR.glob("*.yaml")))
    total += fill(doors.WHAT_IT_DOES_YAML, cat, True, check)
    print(f"{'found' if check else 'filled'} {total} pin(s)")


if __name__ == "__main__":
    main()
