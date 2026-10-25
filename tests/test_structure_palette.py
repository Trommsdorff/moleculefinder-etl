"""Every atom in every 2D drawing carries its CPK colour (trust run 6, 2026-10-25).

The palette used to list ten elements; RDKit drew every other atom label black, and black on
the navy panel nearly vanishes: 160 of 896 drawings, 66 of them entirely (the element pages,
/m/aluminium a faint "Al") and 94 in part (the Ca in calcium carbonate, the K in acesulfame
potassium, and six radicals whose electron dots RDKit always draws black). Garrett's ruling:
the full standard CPK table, so each element's colour keeps meaning something, and one light
fallback only for an element outside it.

The fixtures are the drawings as shipped under recipe 2026-09-07.1, so these tests keep
meaning something after the snapshot has been rebuilt.
"""
from __future__ import annotations

import colorsys
import json
import re
from pathlib import Path

import pytest

from moleculefinder_etl.transform import structures
from moleculefinder_etl.transform.assemble import _carried_svg

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "structures-2026-09-07.1"
MOLECULES = REPO / "data" / "snapshots" / "molecules"
OLD_RECIPE = "2026-09-07.1"

# The Color System Brief §2a hues: the ten the old palette held, kept exactly.
BRIEF = {6: "#bdd6e6", 7: "#6fb1ff", 8: "#ff7a72", 16: "#f2d06b", 15: "#8fd982",
         9: "#7fe0c0", 17: "#7fd98a", 35: "#d98a6a", 53: "#c79af0", 1: "#dbe9f2"}

# Jmol's own colour for each entry that had to be lightened to reach 3:1 on the panel.
LIGHTENED = {19: "#8f40d4", 37: "#702eb0", 46: "#006985", 55: "#57178f", 76: "#266696",
             77: "#175487", 82: "#575961", 85: "#754f45", 87: "#420066", 100: "#b31fba",
             101: "#b30da6", 102: "#bd0d87", 103: "#c70066", 104: "#cc0059", 105: "#d1004f"}

# slug -> (SMILES as exported, the elements whose labels the drawing shows)
CASES = {
    "aluminium": ("[Al]", {13}),
    "calcium-carbonate": ("C(=O)([O-])[O-].[Ca+2]", {8, 20}),
    "acesulfame-potassium": ("CC1=CC(=O)[N-]S(=O)(=O)O1.[K+]", {7, 8, 16, 19}),
    "potassium-iodide": ("[K+].[I-]", {19, 53}),
    "caffeine": ("CN1C=NC2=C1C(=O)N(C(=O)N2C)C", {7, 8}),
    "nitric-oxide": ("[N]=O", {7, 8}),
}

_ATOM_TAG = re.compile(r"<(?:path|ellipse)\b[^>]*\bclass='atom-(\d+)'[^>]*>")
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def _lin(c: int) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(h: str) -> float:
    r, g, b = (int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str = structures.PANEL_HEX) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _hls(h: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def _old_recipe_svg(smiles: str) -> str:
    """What recipe 2026-09-07.1 draws on THIS machine: the ten-colour palette, nothing else."""
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D
    d = rdMolDraw2D.MolDraw2DSVG(400, 300)
    o = d.drawOptions()
    o.updateAtomPalette({z: structures._rgb01(h) for z, h in BRIEF.items()})
    o.singleColourBonds = True
    o.setSymbolColour((*structures._rgb01(BRIEF[6]), 1.0))
    o.clearBackground = False
    d.DrawMolecule(Chem.MolFromSmiles(smiles))
    d.FinishDrawing()
    return d.GetDrawingText()


def _atom_colours(svg: str, smiles: str) -> dict[int, set[str]]:
    """Element -> the colours its atoms' labels and dots are drawn in."""
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    out: dict[int, set[str]] = {}
    for m in _ATOM_TAG.finditer(svg):
        idx = int(m.group(1))
        z = mol.GetAtomWithIdx(idx).GetAtomicNum() if idx < mol.GetNumAtoms() else 1
        out.setdefault(z, set()).update(h.upper() for h in _HEX.findall(m.group(0)))
    return out


def _shipped(slug: str) -> dict:
    smiles, _ = CASES[slug]
    return {"structure_svg": (FIXTURES / f"{slug}.svg").read_text(), "isomeric_smiles": smiles,
            "structure_svg_key": structures.svg_key(smiles, recipe=OLD_RECIPE)}


# ── The table ───────────────────────────────────────────────────────────────
def test_the_ten_brief_colours_are_kept_exactly():
    assert {z: structures.CPK_HEX[z] for z in BRIEF} == BRIEF


def test_every_element_rdkit_can_draw_has_a_readable_colour():
    """1 to 109 from the table, 110 to 118 (past Jmol's table) and the dummy atom the
    fallback; every one at least 3:1 on the panel."""
    assert set(structures.CPK_HEX) == set(range(1, 110))
    for z in range(119):
        assert contrast(structures.atom_hex(z)) >= 3.0, (z, structures.atom_hex(z))
    assert structures.atom_hex(0) == structures.atom_hex(118) == structures.FALLBACK_HEX
    assert structures.FALLBACK_HEX not in structures.CPK_HEX.values()


@pytest.mark.parametrize("z", sorted(LIGHTENED))
def test_a_lightened_colour_was_needed_and_kept_its_hue(z):
    jmol, ours = LIGHTENED[z], structures.CPK_HEX[z]
    assert contrast(jmol) < 3.0 <= contrast(ours)
    (h0, l0, _), (h1, l1, _) = _hls(jmol), _hls(ours)
    assert abs(h0 - h1) * 360 < 0.5 and l1 > l0


def test_only_the_lightened_entries_depart_from_jmol_beyond_the_brief_ten():
    """Each entry's comment names the Jmol colour it was lightened from, and only those do."""
    src = (REPO / "moleculefinder_etl" / "transform" / "structures.py").read_text()
    noted = {int(z): f"#{j}" for z, j in re.findall(r"^\s+(\d+):\s+\"#\w{6}\",\s+# \w+\s+Jmol #(\w{6})",
                                                      src, re.MULTILINE)}
    assert noted == LIGHTENED


def test_the_recipe_version_moved():
    assert structures.RECIPE_VERSION != OLD_RECIPE
    assert OLD_RECIPE in structures.RECOLOURABLE
    s = CASES["caffeine"][0]
    assert structures.svg_key(s) != structures.svg_key(s, recipe=OLD_RECIPE)


# ── The five molecules, and a radical ───────────────────────────────────────
@pytest.mark.parametrize("slug", sorted(CASES))
def test_no_atom_is_black_and_each_element_wears_its_colour(slug):
    smiles, shown = CASES[slug]
    for svg in (_carried_svg(smiles, _shipped(slug))["structure_svg"], structures.svg_for(smiles)):
        assert "#000000" not in svg.upper()
        colours = _atom_colours(svg, smiles)
        for z in shown:
            assert colours.get(z) == {structures.atom_hex(z).upper()}, (slug, z, colours.get(z))
        for z, cs in colours.items():
            assert all(contrast(c) >= 3.0 for c in cs), (slug, z, cs)


def test_the_shipped_drawings_were_black_where_the_old_palette_stopped():
    """The fixtures really are the bug: Al, Ca and K drew black, and so did the radical dot."""
    for slug, z in (("aluminium", 13), ("calcium-carbonate", 20),
                    ("acesulfame-potassium", 19), ("potassium-iodide", 19), ("nitric-oxide", 7)):
        assert "#000000" in _atom_colours((FIXTURES / f"{slug}.svg").read_text(),
                                          CASES[slug][0])[z]


@pytest.mark.parametrize("slug", sorted(CASES))
def test_repainting_an_old_drawing_is_exactly_a_fresh_draw(slug):
    """Both drawn here, so the layout agrees: the repaint must be byte-equal to the recipe.
    (Measured over all 896 drawings on 2026-10-25: 896 equal, 0 differ.)"""
    smiles, _ = CASES[slug]
    assert structures.recolour(_old_recipe_svg(smiles), smiles) == structures.svg_for(smiles)


def test_caffeine_keeps_its_drawing_byte_for_byte():
    """Caffeine has no atom outside the old palette: only its key may move."""
    smiles = CASES["caffeine"][0]
    out = _carried_svg(smiles, _shipped("caffeine"))
    assert out["structure_svg"] == (FIXTURES / "caffeine.svg").read_text()
    assert out["structure_svg_key"] == structures.svg_key(smiles)


def test_a_repainted_drawing_keeps_every_coordinate():
    """Only colours move: strip them and the drawing is the one that shipped."""
    smiles = CASES["acesulfame-potassium"][0]
    old = (FIXTURES / "acesulfame-potassium.svg").read_text()
    new = _carried_svg(smiles, _shipped("acesulfame-potassium"))["structure_svg"]
    assert new != old
    assert _HEX.sub("#", new) == _HEX.sub("#", old)


def test_a_drawing_with_the_current_key_is_not_repainted():
    smiles = CASES["aluminium"][0]
    prior = {"structure_svg": "<svg>as-shipped</svg>", "structure_svg_key": structures.svg_key(smiles)}
    assert _carried_svg(smiles, prior)["structure_svg"] == "<svg>as-shipped</svg>"


# ── The committed snapshot ──────────────────────────────────────────────────
def test_every_committed_drawing_is_readable_and_current():
    """The guard for every future run: no drawing ships an atom in black or in a colour
    under 3:1, and every drawing carries the current recipe's key (so the weekly run, on
    Linux, carries it forward instead of redrawing it)."""
    drawn = 0
    for path in sorted(MOLECULES.glob("*.json")):
        rec = json.loads(path.read_text())
        svg = rec.get("structure_svg")
        if not svg:
            continue
        drawn += 1
        assert "#000000" not in svg.upper(), rec["slug"]
        for m in _ATOM_TAG.finditer(svg):
            for c in _HEX.findall(m.group(0)):
                assert contrast(c) >= 3.0, (rec["slug"], c)
        assert rec["structure_svg_key"] == structures.svg_key(rec["isomeric_smiles"]), rec["slug"]
    assert drawn > 800
