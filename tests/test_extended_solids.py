"""The extended-solids pass (2026-11-26; Garrett's ruling 2 on the 2026-12-care review, 2026-11-15): silicon dioxide
and zinc oxide are drawn with nothing, as titanium dioxide is (seeds/structure_none.yaml, DRAWING-RECIPES section 13).
Brief: ../EXTENDED-SOLIDS-PROMPT.md. The rest of the catalog's extended solids are NOT changed here: they wait for
Garrett's ruling on the review page (web docs/design/extended-solids-review-2026-11.html)."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml

from moleculefinder_etl.config import SEEDS_DIR
from moleculefinder_etl.transform import assemble
from moleculefinder_etl.transform import drawing_guard as DG

SNAP = Path(__file__).resolve().parents[1] / "data" / "snapshots"
SOLIDS = {"silicon-dioxide": ("O2Si", "O=[Si]=O", 24261), "zinc-oxide": ("OZn", "O=[Zn]", 14806)}
CLAIM_WORDS = re.compile(r"\b(only|first|most|leading|largest|world's|never|always)\b", re.IGNORECASE)


def _rec(slug):
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


def test_structure_none_lists_exactly_the_three_ruled_lattices():
    # A new entry removes a live drawing: it comes only with Garrett's ruling and its own review page.
    seed = yaml.safe_load((SEEDS_DIR / "structure_none.yaml").read_text())["molecules"]
    assert set(seed) == {"titanium-dioxide", "silicon-dioxide", "zinc-oxide"}


def test_each_is_drawn_with_nothing_and_keeps_its_formula_unit():
    for slug, (formula, smiles, cid) in SOLIDS.items():
        r = _rec(slug)
        assert r["cid"] == cid
        assert r["structure_svg"] is None and r["structure_svg_key"] is None and r["has_3d"] is False, slug
        assert not r.get("structure_parts") and not r.get("structure_repeat_unit"), slug
        # formula, weight and SMILES stay PubChem's (one formula unit)
        assert r["molecular_formula"] == formula and r["isomeric_smiles"] == smiles and r["molecular_weight"], slug
        # no computed descriptor of a molecule it does not have
        assert all(v is None for k, v in r["descriptors"].items() if k != "confidence"), slug
        assert r["structure_none"] == assemble.structure_none_for(slug)


def test_the_lines_say_network_or_lattice_with_the_formula_unit_and_keep_the_house_rules():
    si = _rec("silicon-dioxide")["structure_none"]["line"]
    zn = _rec("zinc-oxide")["structure_none"]["line"]
    assert si == ("a network of silicon and oxygen with no single molecule, each silicon bonded to four oxygens and "
                  "each oxygen to two silicons; its formula, SiO2, gives the ratio, one silicon to every two oxygens.")
    assert zn == ("a crystal lattice of zinc and oxygen with no single molecule, each zinc among four oxygens; its "
                  "formula, ZnO, gives the ratio, one zinc to each oxygen.")
    for line in (si, zn):
        assert not CLAIM_WORDS.search(line) and "—" not in line and "–" not in line


def test_no_pair_or_pair_drawing_used_their_drawings():
    comparisons = json.loads((SNAP / "comparisons.json").read_text())
    pairs = json.loads((SNAP / "compare_drawings.json").read_text())["pairs"]
    for slug in SOLIDS:
        assert not any(slug in (c.get("a"), c.get("b")) for c in comparisons.values())
        assert not any(slug in key.split("-vs-") for key in pairs)


def test_the_guard_lists_exactly_the_two_drawings_that_leave(tmp_path):
    """Against a shipped snapshot in which both still had their drawings (as on main before this pass), the guard
    lists each removal by name, stops nothing and changes no other count."""
    shipped = tmp_path / "snapshots"
    shutil.copytree(SNAP / "molecules", shipped / "molecules")
    shutil.copy(SNAP / "compare_drawings.json", shipped / "compare_drawings.json")
    for slug in SOLIDS:
        p = shipped / "molecules" / f"{slug}.json"
        r = json.loads(p.read_text())
        r["structure_svg"], r["structure_svg_key"] = "<svg/>", "shipped-key"
        p.write_text(json.dumps(r))
    by_cid, pairs = DG.shipped(SNAP)
    v = DG.check([by_cid[c] for c in sorted(by_cid)], pairs, shipped, allow_seeds=False)
    assert v.stops == []
    # listed in CID order (the guard walks the catalog by CID: zinc oxide 14806, silicon dioxide 24261)
    assert v.made == ["zinc-oxide (structure drawing): removed, it no longer has a drawing",
                      "silicon-dioxide (structure drawing): removed, it no longer has a drawing"]
    assert v.lines[0] == "structure drawings: 901 carried, 0 repainted, 0 drawn, 28 with no drawing"


def test_zinc_oxide_leaves_the_molecule_of_the_week_for_avobenzone():
    # The week needs a drawable molecule (transform/featured.py). Week 22 (2027-05-31) has not run, so no archive
    # page or RSS item moves. Garrett's decision on the review page.
    weeks = yaml.safe_load((SEEDS_DIR / "featured.yaml").read_text())["weeks"]
    by_week = {w["week"]: w for w in weeks}
    assert by_week[22]["slug"] == "avobenzone"
    assert by_week[22]["hook"] == ("Sunscreen season: avobenzone filters long-wave UVA, and sunscreens pair it with a "
                                   "second filter that keeps sunlight from breaking it down.")
    assert not any(w.get("slug") in SOLIDS for w in weeks)
    assert _rec("avobenzone")["structure_svg"]
