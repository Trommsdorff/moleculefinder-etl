"""Every atom in every 2D drawing carries its CPK colour, tuned for the navy panel.

Trust run 6 (2026-10-25): the palette used to list ten elements; RDKit drew every other atom
label black, and black on the navy panel nearly vanishes: 160 of 896 drawings, 66 of them
entirely (the element pages, /m/aluminium a faint "Al") and 94 in part (the Ca in calcium
carbonate, the K in acesulfame potassium, and six radicals whose electron dots RDKit always
draws black). Garrett's ruling: the full standard CPK table, so each element's colour keeps
meaning something, and one light fallback only for an element outside it.

Trust run 7 (2026-10-25): Jmol's colours as they were "vibrate on dark" (calcium neon green,
potassium a dark purple). Garrett's ruling: tune them the way the ten were tuned, by ONE rule,
not by eye: every colour outside the ten is brought into the band the ten occupy in OKLCH.

The fixtures are the drawings as shipped under recipes 2026-09-07.1 (trust run 6's "before")
and 2026-10-25.1 (trust run 7's), so these tests keep meaning something after the snapshot
has been rebuilt.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from moleculefinder_etl.transform import structures
from moleculefinder_etl.transform.assemble import _carried_svg

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"
MOLECULES = REPO / "data" / "snapshots" / "molecules"
OLD_RECIPES = ("2026-09-07.1", "2026-10-25.1")

# The Color System Brief §2a hues: the ten the old palette held, kept exactly.
BRIEF = {6: "#bdd6e6", 7: "#6fb1ff", 8: "#ff7a72", 16: "#f2d06b", 15: "#8fd982",
         9: "#7fe0c0", 17: "#7fd98a", 35: "#d98a6a", 53: "#c79af0", 1: "#dbe9f2"}

# Trust run 6's palette (recipe 2026-10-25.1) differed from Jmol's only here: these 15 were
# lightened in HSL to reach 3:1. Trust run 7 starts again from Jmol's own colour.
LIGHTENED_2026_10_25_1 = {
    19: "#9041d4", 37: "#8c46cf", 46: "#007493", 55: "#923adf", 76: "#296fa3", 77: "#1e6eb0",
    82: "#686a72", 85: "#8d5f53", 87: "#a200fa", 100: "#b51fbc", 101: "#be0eb1",
    102: "#c80e8f", 103: "#d0006a", 104: "#d2005b", 105: "#d40050"}

# Every palette a recipe drew with (the fallback is RDKit's own black for 2026-09-07.1).
OLD_PALETTES = {
    "2026-09-07.1": (BRIEF, None),
    "2026-10-25.1": ({**BRIEF, **structures.JMOL_HEX, **LIGHTENED_2026_10_25_1}, "#ffffff"),
}

# RDKit's close-contact flag: a box in pure red round an atom the layout put too close to
# another, classed with that atom. Not a colour of this palette, and never repainted.
FLAG_HEX = "#FF0000"
HUPERZINE_A = "C/C=C/1\\[C@@H]2CC3=C([C@]1(CC(=C2)C)N)C=CC(=O)N3"

# slug -> (SMILES as exported, the elements whose labels the drawing shows)
CASES = {
    "aluminium": ("[Al]", {13}),
    "calcium-carbonate": ("C(=O)([O-])[O-].[Ca+2]", {8, 20}),
    "acesulfame-potassium": ("CC1=CC(=O)[N-]S(=O)(=O)O1.[K+]", {7, 8, 16, 19}),
    "potassium-iodide": ("[K+].[I-]", {19, 53}),
    "caffeine": ("CN1C=NC2=C1C(=O)N(C(=O)N2C)C", {7, 8}),
    "nitric-oxide": ("[N]=O", {7, 8}),
    "magnesium": ("[Mg]", {12}),
    "gold": ("[Au]", {79}),
}

# The palette each recipe draws with, by fingerprint. A palette change that does not bump
# RECIPE_VERSION would leave drawings carried forward in the old colours beside new ones
# drawn fresh in the new: this fails first.
PALETTE_SHA = {"2026-10-25.2": "5009ad7fdb88b5f6fffbfc23a30d69b599f6fa9f"}

_ATOM_TAG = re.compile(r"<(?:path|ellipse)\b[^>]*\bclass='atom-(\d+)'[^>]*>")
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def _is_flag(tag: str) -> bool:
    return "fill:none" in tag and FLAG_HEX in tag.upper()


def _lin(c: int) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(h: str) -> float:
    r, g, b = (int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str = structures.PANEL_HEX) -> float:
    """Written out here, not imported, so the module's own arithmetic is checked against it."""
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _hue_gap(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _is_grey(h: str) -> bool:
    return len({h.lstrip("#")[i:i + 2] for i in (0, 2, 4)}) == 1


def _old_recipe_svg(smiles: str, recipe: str) -> str:
    """What an older recipe draws on THIS machine, before any repaint."""
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D
    palette, fallback = OLD_PALETTES[recipe]
    d = rdMolDraw2D.MolDraw2DSVG(400, 300)
    o = d.drawOptions()
    rgb = {z: structures._rgb01(h) for z, h in palette.items()}
    if fallback:
        rgb[-1] = rgb[0] = structures._rgb01(fallback)
    o.updateAtomPalette(rgb)
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
        if _is_flag(m.group(0)):
            continue
        idx = int(m.group(1))
        z = mol.GetAtomWithIdx(idx).GetAtomicNum() if idx < mol.GetNumAtoms() else 1
        out.setdefault(z, set()).update(h.upper() for h in _HEX.findall(m.group(0)))
    return out


def _fixture(recipe: str, slug: str) -> str:
    return (FIXTURES / f"structures-{recipe}" / f"{slug}.svg").read_text()


def _shipped(recipe: str, slug: str) -> dict:
    smiles, _ = CASES[slug]
    return {"structure_svg": _fixture(recipe, slug), "isomeric_smiles": smiles,
            "structure_svg_key": structures.svg_key(smiles, recipe=recipe)}


# ── The colour arithmetic ───────────────────────────────────────────────────
def test_oklch_matches_the_published_reference():
    """CSS Color 4's own worked values: sRGB red is oklch(62.80% 0.2577 29.23)."""
    L, C, h = structures.oklch("#ff0000")
    assert (round(L, 4), round(C, 4), round(h, 2)) == (0.628, 0.2577, 29.23)
    L, C, _ = structures.oklch("#ffffff")
    assert abs(L - 1) < 1e-6 and C < 1e-6


def test_the_modules_contrast_is_wcags():
    for h in (*BRIEF.values(), *structures.JMOL_HEX.values(), "#ffffff"):
        assert abs(structures.contrast(h) - contrast(h)) < 1e-9


# ── The band ────────────────────────────────────────────────────────────────
def test_the_band_is_the_box_the_ten_span():
    Ls = {z: structures.oklch(h)[0] for z, h in BRIEF.items()}
    Cs = {z: structures.oklch(h)[1] for z, h in BRIEF.items()}
    assert structures.BAND_L == (Ls[35], Ls[1])       # bromine's lightness to hydrogen's
    assert structures.BAND_C == (Cs[1], Cs[8])        # hydrogen's chroma to oxygen's
    assert structures.BAND_L == (min(Ls.values()), max(Ls.values()))
    assert structures.BAND_C == (min(Cs.values()), max(Cs.values()))


def test_the_comment_at_the_table_states_the_ten_as_measured():
    src = (REPO / "moleculefinder_etl" / "transform" / "structures.py").read_text()
    rows = re.findall(r"(#[0-9a-f]{6})\s+L (\d\.\d{3})\s+C (\d\.\d{3})\s+h\s+(\d+\.\d)", src)
    assert {h for h, *_ in rows} == set(BRIEF.values())
    for h, L, C, hue in rows:
        got = structures.oklch(h)
        assert (f"{got[0]:.3f}", f"{got[1]:.3f}", f"{got[2]:.1f}") == (L, C, hue), h


# ── The table ───────────────────────────────────────────────────────────────
def test_the_ten_brief_colours_are_kept_exactly():
    assert {z: structures.CPK_HEX[z] for z in BRIEF} == BRIEF
    assert structures.BRIEF_HEX == BRIEF


def test_the_source_table_is_jmols_beyond_the_ten():
    """Every element 2 to 109 outside the ten, as Jmol publishes it (spot-checked here; the
    whole table was compared with Jmol's file on 2026-10-25)."""
    assert set(structures.JMOL_HEX) | set(BRIEF) == set(range(1, 110))
    assert not set(structures.JMOL_HEX) & set(BRIEF)
    assert {z: structures.JMOL_HEX[z] for z in (11, 12, 19, 20, 38, 55, 79, 82)} == {
        11: "#ab5cf2", 12: "#8aff00", 19: "#8f40d4", 20: "#3dff00", 38: "#00ff00",
        55: "#57178f", 79: "#ffd123", 82: "#575961"}


def test_every_colour_rdkit_can_draw_lies_inside_the_band_at_3_to_1():
    """1 to 109 from the table, 110 to 118 (past Jmol's table) and the dummy atom the
    fallback; every one inside the band and at least 3:1 on the panel."""
    assert set(structures.CPK_HEX) == set(range(1, 110))
    lo_l, hi_l = structures.BAND_L
    lo_c, hi_c = structures.BAND_C
    for z in range(119):
        h = structures.atom_hex(z)
        L, C, _ = structures.oklch(h)
        assert lo_l <= L <= hi_l and lo_c <= C <= hi_c, (z, h, L, C)
        assert contrast(h) >= 3.0, (z, h)
    assert structures.atom_hex(0) == structures.atom_hex(118) == structures.FALLBACK_HEX


@pytest.mark.parametrize("z", sorted(structures.JMOL_HEX))
def test_each_colour_is_jmols_through_the_one_rule(z):
    """Inside the band already: kept. Otherwise each axis is kept where it was inside the band
    and clamped to the band's edge where it was not (chroma lower only where sRGB has no room
    at that lightness and hue), and the hue is kept, all within one 8-bit step."""
    jmol, ours = structures.JMOL_HEX[z], structures.CPK_HEX[z]
    assert ours == structures.tuned(jmol)
    if structures.in_band(jmol) and contrast(jmol) >= 3.0:
        assert ours == jmol
        return
    (L0, C0, h0), (L1, C1, h1) = structures.oklch(jmol), structures.oklch(ours)
    want_l = min(max(L0, structures.BAND_L[0]), structures.BAND_L[1])
    want_c = min(max(C0, structures.BAND_C[0]), structures.BAND_C[1])
    assert abs(L1 - want_l) < 0.004, (z, L1, want_l)
    assert C1 < want_c + 0.004, (z, C1, want_c)
    if C1 < want_c - 0.004:   # only where the gamut ends first
        assert not structures._in_gamut(L1, want_c, h1), (z, C1, want_c)
    want_h = structures.oklch(BRIEF[6])[2] if _is_grey(jmol) else h0
    assert _hue_gap(h1, want_h) < (1.2 if C1 >= 0.03 else 5.0), (z, h1, want_h)


def test_the_fallback_follows_the_rule():
    """White through the rule is the band's lightest, least coloured corner in carbon's hue:
    hydrogen's own #dbe9f2."""
    assert structures.FALLBACK_HEX == structures.tuned("#ffffff") == BRIEF[1]


def test_the_palette_is_pinned_to_the_recipe_version():
    payload = json.dumps({"palette": sorted(structures.CPK_HEX.items()),
                          "fallback": structures.FALLBACK_HEX})
    assert PALETTE_SHA.get(structures.RECIPE_VERSION) == hashlib.sha1(payload.encode()).hexdigest()


def test_the_repaint_knows_each_older_palette():
    """``recolour`` replaces only the colours an older recipe drew an element in, so it has to
    hold each palette exactly as it shipped."""
    assert {v: structures.RECOLOURABLE[v][0] for v in OLD_RECIPES} == {
        v: OLD_PALETTES[v][0] for v in OLD_RECIPES}
    assert structures.RECOLOURABLE["2026-10-25.1"][1] == "#ffffff"
    assert all(FLAG_HEX.lower() not in c for c in structures._DRAWN_IN.values())


def test_the_recipe_version_moved():
    assert structures.RECIPE_VERSION not in OLD_RECIPES
    assert set(OLD_RECIPES) <= set(structures.RECOLOURABLE)
    s = CASES["caffeine"][0]
    assert all(structures.svg_key(s) != structures.svg_key(s, recipe=v) for v in OLD_RECIPES)


# ── The molecules, and a radical ────────────────────────────────────────────
@pytest.mark.parametrize("recipe", OLD_RECIPES)
@pytest.mark.parametrize("slug", sorted(CASES))
def test_each_label_carries_its_table_colour(recipe, slug):
    smiles, shown = CASES[slug]
    for svg in (_carried_svg(smiles, _shipped(recipe, slug))["structure_svg"],
                structures.svg_for(smiles)):
        assert "#000000" not in svg.upper()
        colours = _atom_colours(svg, smiles)
        assert set(colours) >= shown
        for z, cs in colours.items():
            assert cs == {structures.atom_hex(z).upper()}, (slug, z, cs)


def test_the_shipped_drawings_were_black_where_the_old_palette_stopped():
    """The 2026-09-07.1 fixtures really are trust run 6's bug: Al, Ca, K, Mg and Au drew
    black, and so did the radical dot."""
    for slug, z in (("aluminium", 13), ("calcium-carbonate", 20), ("acesulfame-potassium", 19),
                    ("potassium-iodide", 19), ("nitric-oxide", 7), ("magnesium", 12),
                    ("gold", 79)):
        assert "#000000" in _atom_colours(_fixture("2026-09-07.1", slug), CASES[slug][0])[z]


def test_the_trust_run_6_drawings_wore_jmols_untuned_colours():
    """The 2026-10-25.1 fixtures really are trust run 7's finding: Jmol's neon calcium and
    magnesium, the lightened-only potassium, and aluminium, already in the band, kept."""
    for slug, z, was in (("calcium-carbonate", 20, "#3DFF00"), ("magnesium", 12, "#8AFF00"),
                         ("acesulfame-potassium", 19, "#9041D4"), ("gold", 79, "#FFD123"),
                         ("aluminium", 13, "#BFA6A6")):
        assert _atom_colours(_fixture("2026-10-25.1", slug), CASES[slug][0])[z] == {was}
    assert structures.CPK_HEX[13] == "#bfa6a6"
    assert all(structures.CPK_HEX[z] != structures.JMOL_HEX[z] for z in (12, 19, 20, 79))


@pytest.mark.parametrize("recipe", OLD_RECIPES)
@pytest.mark.parametrize("slug", sorted(CASES))
def test_repainting_an_old_drawing_is_exactly_a_fresh_draw(recipe, slug):
    """Both drawn here, so the layout agrees: the repaint must be byte-equal to the recipe.
    (Measured over all 896 drawings: 896 equal, 0 differ, for 2026-09-07.1 in trust run 6 and
    for 2026-10-25.1 in trust run 7.)"""
    smiles, _ = CASES[slug]
    assert structures.recolour(_old_recipe_svg(smiles, recipe), smiles) == structures.svg_for(smiles)


@pytest.mark.parametrize("recipe", OLD_RECIPES)
def test_caffeine_keeps_its_drawing_byte_for_byte(recipe):
    """Caffeine has no atom outside the ten: only its key may move."""
    smiles = CASES["caffeine"][0]
    out = _carried_svg(smiles, _shipped(recipe, "caffeine"))
    assert out["structure_svg"] == _fixture("2026-09-07.1", "caffeine") == _fixture(recipe, "caffeine")
    assert out["structure_svg_key"] == structures.svg_key(smiles)


@pytest.mark.parametrize("recipe", OLD_RECIPES)
@pytest.mark.parametrize("slug", ["acesulfame-potassium", "calcium-carbonate", "gold"])
def test_a_repainted_drawing_keeps_every_coordinate(recipe, slug):
    """Only colours move: strip them and the drawing is the one that shipped."""
    smiles = CASES[slug][0]
    old = _fixture(recipe, slug)
    new = _carried_svg(smiles, _shipped(recipe, slug))["structure_svg"]
    assert new != old
    assert _HEX.sub("#", new) == _HEX.sub("#", old)


def test_rdkits_close_contact_flag_is_left_as_drawn():
    """Huperzine A uses only the ten, so its drawing must not change by a byte, and the
    close-contact box its shipped layout carries (one of 14 drawings with one; rdkit 2026.09.1
    lays it out without the contact) is not an atom colour to repaint."""
    shipped = _fixture("2026-10-25.1", "huperzine-a")
    assert sum(_is_flag(m.group(0)) for m in _ATOM_TAG.finditer(shipped)) == 1
    prior = {"structure_svg": shipped, "isomeric_smiles": HUPERZINE_A,
             "structure_svg_key": structures.svg_key(HUPERZINE_A, recipe="2026-10-25.1")}
    assert _carried_svg(HUPERZINE_A, prior)["structure_svg"] == shipped


def test_a_drawing_with_the_current_key_is_not_repainted():
    smiles = CASES["aluminium"][0]
    prior = {"structure_svg": "<svg>as-shipped</svg>", "structure_svg_key": structures.svg_key(smiles)}
    assert _carried_svg(smiles, prior)["structure_svg"] == "<svg>as-shipped</svg>"


# ── The committed snapshot ──────────────────────────────────────────────────
def test_every_committed_drawing_is_in_its_table_colours_and_current():
    """The guard for every future run: every atom label and dot in every drawing wears its
    element's table colour (so none is black, untuned, outside the band or under 3:1), and
    every drawing carries the current recipe's key (so the weekly run, on Linux, carries it
    forward instead of redrawing it). RDKit's close-contact boxes are counted, not repainted."""
    from rdkit import Chem
    drawn = flagged = 0
    for path in sorted(MOLECULES.glob("*.json")):
        rec = json.loads(path.read_text())
        svg = rec.get("structure_svg")
        if not svg:
            continue
        drawn += 1
        assert "#000000" not in svg.upper(), rec["slug"]
        mol = Chem.MolFromSmiles(rec["isomeric_smiles"])
        flags = 0
        for m in _ATOM_TAG.finditer(svg):
            if _is_flag(m.group(0)):
                flags += 1
                continue
            idx = int(m.group(1))
            z = mol.GetAtomWithIdx(idx).GetAtomicNum() if idx < mol.GetNumAtoms() else 1
            assert {c.upper() for c in _HEX.findall(m.group(0))} == {structures.atom_hex(z).upper()}, \
                (rec["slug"], z)
        flagged += flags > 0
        assert rec["structure_svg_key"] == structures.svg_key(rec["isomeric_smiles"]), rec["slug"]
    assert drawn > 800
    assert flagged == 14
