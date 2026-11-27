"""Build-time 2D SVG per molecule (crawlable, no-JS, instant first paint).

CPK-colored, palette-tuned for the dark Blueprint panel (Color System Brief §2a):
a uniform light-blue-gray skeleton with color reserved for heteroatom labels, on a
transparent background. Verified recipe for RDKit MolDraw2DSVG: updateAtomPalette
(carbon = key 6) + singleColourBonds + setSymbolColour(carbon) so bonds stay one
light color while N/O/S/... labels carry their element hue; clearBackground=False
so the SVG sits on the panel with no white box (the web CSS no longer inverts).

**Every element has its colour (trust run 6, 2026-10-25).** The palette used to list ten
elements and RDKit drew every other atom label in black, which nearly vanishes on the navy
panel (160 of 896 drawings: the element pages, the Ca in calcium carbonate, the K in
acesulfame potassium). It is now the full CPK table, see ``CPK_HEX``. RDKit also draws
radical electrons as black dots whatever the palette says (no draw option reaches them), so
``recolour`` paints every atom's label and dots in that atom's colour.

**Every colour outside the ten is tuned by one rule (trust run 7, 2026-10-25).** Raw CPK
"vibrates on dark" (the brief), which is why the ten were tuned; trust run 6 took Jmol's
colours as they were, so calcium drew neon green and potassium a dark purple. Now each Jmol
colour is brought into the band the ten occupy in OKLCH, see ``tuned``.

**The rendered SVG is a stored artifact, not a re-derived one** (determinism, 2026-09-07).
RDKit's 2D depiction is deterministic for a given SMILES *on a given platform build*, but
for ~7% of the catalog (fused/bridged polycyclics, where the layout falls through to a
numerical minimiser) the macOS-arm64 and Linux-x86_64 wheels converge on different
coordinates. Measured: rdkit 2026.03.3 and 2026.03.6 on macOS agree on all 769 structures,
and both disagree with the Linux CI output on the same 53 — so the variable is the platform,
not the version, and pinning the version fixes nothing. Instead `svg_key()` fingerprints the
inputs and the caller reuses the previously exported SVG whenever the fingerprint matches, so
a molecule is drawn once and then carried forward byte-for-byte. Bump RECIPE_VERSION to force
a redraw of the whole catalog when the recipe below actually changes. (The version does matter
across releases: rdkit 2026.09.1 lays out 406 of the 896 shipped drawings differently, benzene
mirrored top to bottom, which is why a palette-only change repaints instead, see
``RECOLOURABLE``.)
"""
from __future__ import annotations

import hashlib
import itertools
import math
import re

# The panel every drawing sits on, and the lightest of the surfaces that show one (the
# molecule page's stage is --bg-deep #09161e, the cards and the embed are darker or equal).
PANEL_HEX = "#0e2233"

# The Color System Brief §2a hues, tuned by hand for the dark panel. Kept exactly as shipped,
# so the drawings that use only them never change, and they define the band below.
BRIEF_HEX: dict[int, str] = {
    6: "#bdd6e6",   # carbon / bonds (light blue-gray) — also the single bond color
    7: "#6fb1ff",   # nitrogen (azure)
    8: "#ff7a72",   # oxygen (warm red)
    16: "#f2d06b",  # sulfur (yellow)
    15: "#8fd982",  # phosphorus (green)
    9: "#7fe0c0",   # fluorine (pale teal)
    17: "#7fd98a",  # chlorine (green)
    35: "#d98a6a",  # bromine (rust)
    53: "#c79af0",  # iodine (violet)
    1: "#dbe9f2",   # hydrogen (if shown; usually implicit)
}

# Jmol's CPK colour for every other element, 2 He to 109 Mt, verbatim: the standard table, so
# an element's colour keeps meaning something (Garrett's ruling, 2026-10-25; Color-as-
# Information). Source: jmol.sourceforge.net/jscolors/jmol_constants.js (Jmol 12.1.15 rev
# 14469), compared entry by entry with the published file on 2026-10-25. No drawing uses these
# as they are: each goes through ``tuned``.
JMOL_HEX: dict[int, str] = {
    2: "#d9ffff", 3: "#cc80ff", 4: "#c2ff00", 5: "#ffb5b5", 10: "#b3e3f5",  # He Li Be B Ne
    11: "#ab5cf2", 12: "#8aff00", 13: "#bfa6a6", 14: "#f0c8a0", 18: "#80d1e3",  # Na Mg Al Si Ar
    19: "#8f40d4", 20: "#3dff00", 21: "#e6e6e6", 22: "#bfc2c7", 23: "#a6a6ab",  # K Ca Sc Ti V
    24: "#8a99c7", 25: "#9c7ac7", 26: "#e06633", 27: "#f090a0", 28: "#50d050",  # Cr Mn Fe Co Ni
    29: "#c88033", 30: "#7d80b0", 31: "#c28f8f", 32: "#668f8f", 33: "#bd80e3",  # Cu Zn Ga Ge As
    34: "#ffa100", 36: "#5cb8d1", 37: "#702eb0", 38: "#00ff00", 39: "#94ffff",  # Se Kr Rb Sr Y
    40: "#94e0e0", 41: "#73c2c9", 42: "#54b5b5", 43: "#3b9e9e", 44: "#248f8f",  # Zr Nb Mo Tc Ru
    45: "#0a7d8c", 46: "#006985", 47: "#c0c0c0", 48: "#ffd98f", 49: "#a67573",  # Rh Pd Ag Cd In
    50: "#668080", 51: "#9e63b5", 52: "#d47a00", 54: "#429eb0", 55: "#57178f",  # Sn Sb Te Xe Cs
    56: "#00c900", 57: "#70d4ff", 58: "#ffffc7", 59: "#d9ffc7", 60: "#c7ffc7",  # Ba La Ce Pr Nd
    61: "#a3ffc7", 62: "#8fffc7", 63: "#61ffc7", 64: "#45ffc7", 65: "#30ffc7",  # Pm Sm Eu Gd Tb
    66: "#1fffc7", 67: "#00ff9c", 68: "#00e675", 69: "#00d452", 70: "#00bf38",  # Dy Ho Er Tm Yb
    71: "#00ab24", 72: "#4dc2ff", 73: "#4da6ff", 74: "#2194d6", 75: "#267dab",  # Lu Hf Ta W Re
    76: "#266696", 77: "#175487", 78: "#d0d0e0", 79: "#ffd123", 80: "#b8b8d0",  # Os Ir Pt Au Hg
    81: "#a6544d", 82: "#575961", 83: "#9e4fb5", 84: "#ab5c00", 85: "#754f45",  # Tl Pb Bi Po At
    86: "#428296", 87: "#420066", 88: "#007d00", 89: "#70abfa", 90: "#00baff",  # Rn Fr Ra Ac Th
    91: "#00a1ff", 92: "#008fff", 93: "#0080ff", 94: "#006bff", 95: "#545cf2",  # Pa U Np Pu Am
    96: "#785ce3", 97: "#8a4fe3", 98: "#a136d4", 99: "#b31fd4", 100: "#b31fba",  # Cm Bk Cf Es Fm
    101: "#b30da6", 102: "#bd0d87", 103: "#c70066", 104: "#cc0059", 105: "#d1004f",  # Md No Lr Rf Db
    106: "#d90045", 107: "#e00038", 108: "#e6002e", 109: "#eb0026",  # Sg Bh Hs Mt
}


# ── Colour arithmetic: sRGB, OKLab/OKLCH (Björn Ottosson, 2020), WCAG contrast ─────────────
def _rgb01(hex_str: str) -> tuple[float, float, float]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _encoded(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _oklab_of_linear(r: float, g: float, b: float) -> tuple[float, float, float]:
    l_ = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m_ = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s_ = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _linear_of_oklch(L: float, C: float, h: float) -> tuple[float, float, float]:
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
            -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
            -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)


def oklab(hex_str: str) -> tuple[float, float, float]:
    return _oklab_of_linear(*(_linear(c) for c in _rgb01(hex_str)))


def oklch(hex_str: str) -> tuple[float, float, float]:
    """(lightness 0 to 1, chroma, hue in degrees) of an sRGB hex colour."""
    L, a, b = oklab(hex_str)
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def contrast(hex_str: str, against: str = PANEL_HEX) -> float:
    """WCAG 2 contrast ratio of two sRGB colours."""
    def lum(h: str) -> float:
        r, g, b = (_linear(c) for c in _rgb01(h))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    hi, lo = sorted((lum(hex_str), lum(against)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# ── The band (trust run 7, 2026-10-25) ──────────────────────────────────────────────────────
# Garrett's ruling: tune every colour outside the ten the way the ten were tuned, by ONE rule,
# not by eye. The ten measured in OKLCH (lightness L from 0 black to 1 white; chroma C, the
# distance from grey; hue h in degrees):
#     C   #bdd6e6  L 0.863  C 0.035  h 235.9      F   #7fe0c0  L 0.838  C 0.104  h 170.3
#     N   #6fb1ff  L 0.749  C 0.132  h 253.5      Cl  #7fd98a  L 0.809  C 0.140  h 146.9
#     O   #ff7a72  L 0.733  C 0.164  h  25.4      Br  #d98a6a  L 0.708  C 0.107  h  42.7
#     S   #f2d06b  L 0.867  C 0.126  h  91.0      I   #c79af0  L 0.759  C 0.129  h 307.6
#     P   #8fd982  L 0.816  C 0.139  h 140.8      H   #dbe9f2  L 0.926  C 0.019  h 235.7
# The band is the box they span on each axis: lightness from bromine's 0.708 to hydrogen's
# 0.926, chroma from hydrogen's 0.019 to oxygen's 0.164. Hue is not banded (the ten span the
# wheel). OKLCH because its L and C track what the eye sees evenly across hues, which HSL's do
# not (HSL calls #00ff00 and #0000ff equally light). Carbon and hydrogen count: they are the
# brief's tuned neutrals, and without them the chroma floor would be 0.104 and every grey
# metal (silver, platinum, mercury) would be forced into a colour. ``BAND_L``/``BAND_C`` are
# computed from BRIEF_HEX, so the band cannot drift from the ten.
BAND_L: tuple[float, float] = (min(oklch(h)[0] for h in BRIEF_HEX.values()),
                               max(oklch(h)[0] for h in BRIEF_HEX.values()))
BAND_C: tuple[float, float] = (min(oklch(h)[1] for h in BRIEF_HEX.values()),
                               max(oklch(h)[1] for h in BRIEF_HEX.values()))
CONTRAST_FLOOR = 3.0   # WCAG, graphical objects, against PANEL_HEX


def in_band(hex_str: str) -> bool:
    L, C, _ = oklch(hex_str)
    return BAND_L[0] <= L <= BAND_L[1] and BAND_C[0] <= C <= BAND_C[1]


def _in_gamut(L: float, C: float, h: float) -> bool:
    return all(-1e-9 <= c <= 1 + 1e-9 for c in _linear_of_oklch(L, C, h))


def _hex_of_oklch(L: float, C: float, h: float) -> str:
    return "#" + "".join(f"{round(_encoded(min(1.0, max(0.0, c))) * 255):02x}"
                         for c in _linear_of_oklch(L, C, h))


def tuned(hex_str: str) -> str:
    """The rule: ``hex_str`` brought into the band, its hue kept, at 3:1 on the panel.

    1. A colour already inside the band and at 3:1 is kept exactly.
    2. Its OKLCH hue is kept. A grey (R = G = B) has no hue and takes carbon's (235.9), the
       blue-grey the brief gave its own neutrals.
    3. Lightness and chroma are clamped into the band.
    4. If that point lies outside sRGB, chroma is lowered (same lightness and hue) to the edge.
    5. Lightness is raised by the least that reaches 3:1. (The band's floor already clears it:
       nothing this rule produces today is under 5.7:1, so this step moves nothing yet.)
    6. The result is the 8-bit colour nearest that point (OKLab distance) that is still inside
       the band and at 3:1. Rounding to 8 bits moves a hue by at most 1.2 degrees (astatine,
       chroma 0.054), and by up to 4.7 on the near greys held at the chroma floor (lead).
    """
    if in_band(hex_str) and contrast(hex_str) >= CONTRAST_FLOOR:
        return hex_str
    r, g, b = _rgb01(hex_str)
    L, C, h = oklch(hex_str)
    if r == g == b:
        h = oklch(BRIEF_HEX[6])[2]
    L = min(max(L, BAND_L[0]), BAND_L[1])
    C = min(max(C, BAND_C[0]), BAND_C[1])

    def fit(L: float, C: float) -> float:
        lo, hi = 0.0, C
        if _in_gamut(L, C, h):
            return C
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if _in_gamut(L, mid, h) else (lo, mid)
        return lo

    C = fit(L, C)
    while contrast(_hex_of_oklch(L, C, h)) < CONTRAST_FLOOR and L < BAND_L[1]:
        L = min(L + 0.0005, BAND_L[1])
        C = fit(L, C)

    target = (L, C * math.cos(math.radians(h)), C * math.sin(math.radians(h)))
    near = _rgb01(_hex_of_oklch(L, C, h))
    best: tuple[float, str] | None = None
    for d in itertools.product(range(-2, 3), repeat=3):
        rgb = [round(c * 255) + dc for c, dc in zip(near, d)]
        if not all(0 <= c <= 255 for c in rgb):
            continue
        cand = "#" + "".join(f"{c:02x}" for c in rgb)
        if not in_band(cand) or contrast(cand) < CONTRAST_FLOOR:
            continue
        dist = math.dist(oklab(cand), target)
        if best is None or dist < best[0]:
            best = (dist, cand)
    if best is None:
        raise ValueError(f"no 8-bit colour near {hex_str} fits the band at 3:1")
    return best[1]


# CPK atom colours as hex, keyed by atomic number: the ten as the brief tuned them, every other
# element 2 to 109 as Jmol has it, through the rule. Before and after for every colour the rule
# moves: ETL CLAUDE.md, "Trust run 7". tests/test_structure_palette.py pins all of this.
CPK_HEX: dict[int, str] = {**BRIEF_HEX, **{z: tuned(h) for z, h in JMOL_HEX.items()}}

# The colour for an atom the table does not list: elements 110-118 (Jmol stops at 109) and a
# dummy atom ("*"). RDKit's own defaults there are black (palette key -1) and near black (key
# 0), the very colours this palette exists to keep off the navy panel, so both keys point here.
# It follows the same rule: white through ``tuned`` comes out as hydrogen's #dbe9f2 (the
# band's lightest, least coloured corner, in carbon's hue). No catalog molecule uses it.
FALLBACK_HEX = tuned("#ffffff")


# Bump when anything below changes the pixels: the palette, the draw options, the canvas.
# Every molecule redraws on the next run, which is the point.
RECIPE_VERSION = "2026-10-25.2"

# Earlier recipes whose drawings differ from this one ONLY in colour (same draw options, same
# canvas), each with the colours it drew atoms in: (palette, colour for an unlisted element).
# ``assemble._carried_svg`` repaints such a drawing with ``recolour`` instead of redrawing it,
# so a palette change moves no atom. A palette-only change in future adds the outgoing recipe
# here with its palette.
# 2026-09-07.1: the ten; everything outside them, and every radical dot, black.
# 2026-10-25.1: the ten plus Jmol's table as it is, 15 entries lightened in HSL to reach 3:1.
RECOLOURABLE: dict[str, tuple[dict[int, str], str]] = {
    "2026-09-07.1": (BRIEF_HEX, "#000000"),
    "2026-10-25.1": ({**BRIEF_HEX, **JMOL_HEX,
                      19: "#9041d4", 37: "#8c46cf", 46: "#007493", 55: "#923adf", 76: "#296fa3",
                      77: "#1e6eb0", 82: "#686a72", 85: "#8d5f53", 87: "#a200fa", 100: "#b51fbc",
                      101: "#be0eb1", 102: "#c80e8f", 103: "#d0006a", 104: "#d2005b",
                      105: "#d40050"}, "#ffffff"),
}


def drawn_smiles(rec: dict | None) -> str | None:
    """The SMILES a record's drawing is drawn from: its curated display structure when it has one
    (phase 3A, seeds/structure_display.yaml: a sugar drawn as the ring it is in water), else its
    isomeric SMILES. Every drawing recipe (the structure, its parts, its pairs) and the drawing
    guard read this, never ``isomeric_smiles`` directly; the record's identifiers stay its own."""
    rec = rec or {}
    return (rec.get("structure_display") or {}).get("smiles") or rec.get("isomeric_smiles")


def ring_opened(smiles: str) -> str | None:
    """The open chain of a cyclic sugar (a hemiacetal or hemiketal ring): the bond from the anomeric
    carbon (a ring carbon bearing the ring oxygen and an OH) to the ring oxygen broken, that OH made
    the C=O, the anomeric carbon's stereo dropped. Canonical isomeric SMILES, or None when the
    molecule has not exactly one such carbon."""
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    hits = mol.GetSubstructMatches(Chem.MolFromSmarts("[CX4;R]([OX2;R])[OX2H1;!R]"))
    if len(hits) != 1:
        return None
    c, o_ring, o_h = hits[0]
    rw = Chem.RWMol(mol)
    rw.RemoveBond(c, o_ring)
    rw.GetBondBetweenAtoms(c, o_h).SetBondType(Chem.BondType.DOUBLE)
    rw.GetAtomWithIdx(c).SetChiralTag(Chem.ChiralType.CHI_UNSPECIFIED)
    for i in (c, o_ring, o_h):
        a = rw.GetAtomWithIdx(i)
        a.SetNoImplicit(False)
        a.SetNumExplicitHs(0)
    Chem.SanitizeMol(rw)
    Chem.AssignStereochemistry(rw, cleanIt=True, force=True)
    return Chem.MolToSmiles(rw)


def ring_opens_to(ring_smiles: str, chain_smiles: str) -> bool:
    """True when ``ring_smiles`` is the ring form of ``chain_smiles``: same formula, and the ring
    opened at its anomeric carbon is the chain, every stereocentre included (phase 3A)."""
    from rdkit import Chem
    from rdkit.Chem.rdMolDescriptors import CalcMolFormula

    ring, chain = Chem.MolFromSmiles(ring_smiles or ""), Chem.MolFromSmiles(chain_smiles or "")
    if ring is None or chain is None or CalcMolFormula(ring) != CalcMolFormula(chain):
        return False
    return ring_opened(ring_smiles) == Chem.MolToSmiles(chain)


def _frozen_without_metal_bonds(mol, metal_idx: int):
    """A copy of ``mol`` with every atom's hydrogen count frozen and every bond to the atom ``metal_idx``
    deleted (the wrong-drawings pass, 2026-11-26). Returns (copy, the metal's former neighbours)."""
    from rdkit import Chem

    rw = Chem.RWMol(mol)
    for a in rw.GetAtoms():
        a.SetNumExplicitHs(a.GetTotalNumHs())
        a.SetNoImplicit(True)
    nbrs = sorted(n.GetIdx() for n in rw.GetAtomWithIdx(metal_idx).GetNeighbors())
    for n in nbrs:
        rw.RemoveBond(metal_idx, n)
    return rw, nbrs


def metal_ring(mol, a: int, b: int, metal_idx: int, most: int = 8) -> list[int] | None:
    """The smallest ring through the bond a-b that passes through the metal, as atoms in order from a round to b
    (a, ..., metal, ..., b), or None when there is none of ``most`` atoms or fewer (the cobalamins pass, ruling 4(e)).
    Every bond counts, a dative one included (RDKit's own ring perception leaves dative bonds out)."""
    from collections import deque

    def path(src, dst, banned):
        prev, todo = {src: None}, deque([src])
        while todo:
            x = todo.popleft()
            if x == dst:
                out = [x]
                while prev[out[-1]] is not None:
                    out.append(prev[out[-1]])
                return out[::-1]
            for nb in mol.GetAtomWithIdx(x).GetNeighbors():
                y = nb.GetIdx()
                if y not in prev and y not in banned:
                    prev[y] = x
                    todo.append(y)
        return None

    best = None
    first = path(a, metal_idx, {b})
    if first is not None:
        second = path(metal_idx, b, {a, *first[:-1]})
        if second is not None:
            best = first + second[1:]
    second = path(b, metal_idx, {a})
    if second is not None:
        first = path(metal_idx, a, {b, *second[:-1]})
        if first is not None and (best is None or len(second) + len(first) - 1 < len(best)):
            best = (second + first[1:])[::-1]
    return best if best is not None and len(best) <= most else None


def _top_group(mol, metal_idx: int, top: str) -> list[int] | None:
    """The atoms of the group on top of the metal: the metal's one neighbour the pattern ``top`` matches (its first
    atom) and everything beyond it away from the metal; None unless exactly one neighbour matches."""
    from rdkit import Chem

    hits = {h[0] for h in mol.GetSubstructMatches(Chem.MolFromSmarts(top))} & {
        n.GetIdx() for n in mol.GetAtomWithIdx(metal_idx).GetNeighbors()}
    if len(hits) != 1:
        return None
    seen, todo = set(hits), list(hits)
    while todo:
        for nb in mol.GetAtomWithIdx(todo.pop()).GetNeighbors():
            if nb.GetIdx() not in seen and nb.GetIdx() != metal_idx:
                seen.add(nb.GetIdx())
                todo.append(nb.GetIdx())
    return sorted(seen)


def skeleton_key(display: str, metal: str, top: str) -> str | None:
    """The display structure with its top group removed, as one string that two drawings share exactly when they are
    the same skeleton: the same atoms, bonds, hydrogens, charges and every stereocentre and double-bond geometry, the
    bonds and charges of the rings the metal closes (eight atoms or fewer: a corrin's conjugated ring and the metal's
    own bonds) compared as one conjugated system, so two records that write the corrin's double bonds and its N- in
    different, equivalent places give the same key (the cobalamins pass, ruling 4(d)). None when it cannot be made."""
    from rdkit import Chem

    m = Chem.MolFromSmiles(display or "")
    if m is None:
        return None
    ms = [a.GetIdx() for a in m.GetAtoms() if a.GetSymbol() == metal]
    if len(ms) != 1:
        return None
    grp = _top_group(m, ms[0], top)
    if grp is None:
        return None
    rw = Chem.RWMol(m)
    for a in rw.GetAtoms():
        a.SetNumExplicitHs(a.GetTotalNumHs())
        a.SetNoImplicit(True)
    for i in sorted(grp, reverse=True):
        rw.RemoveAtom(i)
    sk = rw.GetMol()
    sk.UpdatePropertyCache(False)
    metal_idx = next(a.GetIdx() for a in sk.GetAtoms() if a.GetSymbol() == metal)
    chelate = {metal_idx}
    for b in sk.GetBonds():
        ring = metal_ring(sk, b.GetBeginAtomIdx(), b.GetEndAtomIdx(), metal_idx)
        if ring:
            chelate.update(ring)
    flat = Chem.RWMol(sk)
    for b in flat.GetBonds():
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        if i in chelate and j in chelate:
            b.SetBondType(Chem.BondType.SINGLE)
            b.SetIsAromatic(False)
            b.SetStereo(Chem.BondStereo.STEREONONE)
    for i in chelate:
        flat.GetAtomWithIdx(i).SetFormalCharge(0)
        flat.GetAtomWithIdx(i).SetIsAromatic(False)
    out = flat.GetMol()
    out.UpdatePropertyCache(False)
    return Chem.MolToSmiles(out)


def _geometries(mol) -> dict[tuple[int, int], tuple[bool, int, int]]:
    """Every double bond whose geometry the mol states, as RDKit reads it from the SMILES (a double bond in a ring of
    fewer than eight atoms has none): (lower atom, higher atom) -> (cis, the neighbour on the lower atom's side, the
    neighbour on the higher's) that the cis or trans is stated about."""
    from rdkit import Chem

    stated = {b.GetIdx() for b in mol.GetBonds() if b.GetBondType() == Chem.BondType.DOUBLE
              and b.GetStereo() not in (Chem.BondStereo.STEREONONE, Chem.BondStereo.STEREOANY)}
    m = Chem.Mol(mol)
    Chem.SetBondStereoFromDirections(m)                    # E or Z as cis or trans about the marked neighbours
    out = {}
    for b in m.GetBonds():
        if b.GetIdx() not in stated:
            continue
        st = b.GetStereo()
        s1, s2 = list(b.GetStereoAtoms())
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        if s1 not in [x.GetIdx() for x in m.GetAtomWithIdx(i).GetNeighbors()]:
            s1, s2 = s2, s1
        if st not in (Chem.BondStereo.STEREOCIS, Chem.BondStereo.STEREOTRANS):
            raise ValueError("a double bond's geometry could not be read as cis or trans")
        cis = st == Chem.BondStereo.STEREOCIS
        out[(i, j) if i < j else (j, i)] = (cis, s1, s2) if i < j else (cis, s2, s1)
    return out


def metal_bonds_problems(display: str, record: str, metal: str, bonded: list[dict],
                         charges: list[dict], *, top: str | None = None,
                         reference: tuple[str, str] | None = None) -> list[str]:
    """Why ``display`` is not ``record`` with its metal's bonds drawn in, or [] when it is (the wrong-drawings pass,
    2026-11-26; seeds/structure_display.yaml ``metal_bonds``). PubChem's one-line structure keeps a metal apart from
    the atoms it bonds (cisplatin ``N.N.Cl[Pt]Cl``); the display structure bonds them. Proven here, at every build:

    1. the display structure has the record's formula and overall charge (``CalcMolFormula`` carries the charge);
    2. there is exactly one ``metal`` atom in each, and the atoms bonded to it in the display are exactly the atoms
       ``bonded`` names: each entry {smarts, count}, the pattern's FIRST atom being the one bonded to the metal (so a
       cyanide bonded by its nitrogen, or an ammine missing, fails);
    3. every bond the record itself gives the metal (cisplatin's two Pt-Cl) is in the display too;
    4. deleting the bonds to the metal from both gives the same pieces: same atoms, same bonds, same hydrogens,
       every stereocentre and double-bond geometry as the record has it. Formal charges may differ only on the
       metal and the atoms bonded to it, and only as ``charges`` lists them, each {element, record, drawn}: the
       charges are set back to the record's and the two must then be identical (every way of choosing which
       bonded atom of that element carries a listed change is tried; one must give the record).

    Two narrow allowances, added for the cobalamins (2026-11-26, brief ../COBALAMINS-PROMPT.md, ruling 4), each
    proved here, never assumed:
    (e) a double bond whose geometry the record specifies may go unmarked in the drawing only where it sits inside a
        ring of eight atoms or fewer that the metal closes (``metal_ring``), and only when the record's geometry is the
        one that ring forces (the ring's own neighbours on the two ends cis). Anywhere else a dropped geometry fails.
    (d) a stereocentre the record leaves unspecified may be drawn only when ``reference`` is given (the entry names
        ``stereo_from``: the reference entry's display SMILES and its ``top`` pattern) and the drawing's skeleton, with
        its ``top`` group removed, is the reference's skeleton, stereo included (``skeleton_key``). Every centre the
        record DOES specify must be the drawing's, as before.
    """
    from rdkit import Chem
    from rdkit.Chem.rdMolDescriptors import CalcMolFormula

    d, r = Chem.MolFromSmiles(display or ""), Chem.MolFromSmiles(record or "")
    if d is None or r is None:
        return ["the display structure or the record's SMILES does not parse"]
    out = []
    if CalcMolFormula(d) != CalcMolFormula(r):
        out.append(f"formula {CalcMolFormula(d)} is not the record's {CalcMolFormula(r)}")
    if Chem.GetFormalCharge(d) != Chem.GetFormalCharge(r):
        out.append(f"overall charge {Chem.GetFormalCharge(d)} is not the record's {Chem.GetFormalCharge(r)}")
    dm = [a.GetIdx() for a in d.GetAtoms() if a.GetSymbol() == metal]
    rm = [a.GetIdx() for a in r.GetAtoms() if a.GetSymbol() == metal]
    if len(dm) != 1 or len(rm) != 1:
        return out + [f"needs exactly one {metal} in each (display {len(dm)}, record {len(rm)})"]
    dm, rm = dm[0], rm[0]
    # 2. the metal's partners are exactly the named atoms
    named: list[int] = []
    for b in bonded:
        patt = Chem.MolFromSmarts(b["smarts"])
        hits = sorted({h[0] for h in d.GetSubstructMatches(patt)}
                      & {n.GetIdx() for n in d.GetAtomWithIdx(dm).GetNeighbors()})
        if len(hits) != int(b["count"]):
            out.append(f"{b['smarts']} bonded to {metal}: {len(hits)}, expected {b['count']}")
        named += hits
    partners = sorted(n.GetIdx() for n in d.GetAtomWithIdx(dm).GetNeighbors())
    if sorted(named) != partners:
        out.append(f"{metal} is bonded to {len(partners)} atoms, the entry names {len(named)}")
    if out:
        return out
    dfree, dn = _frozen_without_metal_bonds(d, dm)
    rfree, rn = _frozen_without_metal_bonds(r, rm)

    def settled(m):
        m = Chem.Mol(m)
        m.UpdatePropertyCache(False)
        Chem.SanitizeMol(m)
        Chem.AssignStereochemistry(m, cleanIt=True, force=True)
        return m

    # 4. charges back to the record's, every way the listed changes can fall on the bonded atoms
    changes = [c for c in charges if c["element"] != metal]
    metal_change = [c for c in charges if c["element"] == metal]
    if len(metal_change) > 1:
        return [f"{metal}'s charge is listed twice"]
    m_atom = dfree.GetAtomWithIdx(dm)
    if metal_change:
        if m_atom.GetFormalCharge() != int(metal_change[0]["drawn"]):
            return [f"{metal} is drawn with charge {m_atom.GetFormalCharge()}, the entry says {metal_change[0]['drawn']}"]
        m_atom.SetFormalCharge(int(metal_change[0]["record"]))
    rset = settled(rfree)
    want = Chem.MolToSmiles(rset, isomericSmiles=False)
    choices = []
    for c in changes:
        cands = [i for i in dn if dfree.GetAtomWithIdx(i).GetSymbol() == c["element"]
                 and dfree.GetAtomWithIdx(i).GetFormalCharge() == int(c["drawn"])]
        choices.append(cands)
    match = None
    from rdkit.rdBase import BlockLogs
    quiet = BlockLogs()                                    # a wrong pick's valence complaint is not news
    for pick in itertools.product(*choices) if choices else [()]:
        if len(set(pick)) != len(pick):
            continue
        trial = Chem.RWMol(dfree)
        for i, c in zip(pick, changes):
            trial.GetAtomWithIdx(i).SetFormalCharge(int(c["record"]))
        try:
            got = settled(trial)
        except Chem.rdchem.MolSanitizeException:          # a wrong pick leaves an impossible valence
            got = None
        if got is not None and Chem.MolToSmiles(got, isomericSmiles=False) == want:
            match = got
            break
    del quiet
    if match is None:
        return [(f"with the bonds to {metal} deleted and the listed charges set back, it is not the record's own "
                 f"pieces {Chem.MolToSmiles(rset)}")]
    amap = match.GetSubstructMatch(rset)                    # record atom -> display atom (stereo compared below)
    if len(amap) != r.GetNumAtoms():
        return ["the pieces match as SMILES but not atom for atom"]
    # 4, stereo. Double bonds, one by one: every geometry the record gives is the drawing's (cis or trans about the
    # same neighbours), the drawing gives none the record does not, and (e): a geometry the drawing leaves unmarked is
    # allowed only in a ring of eight atoms or fewer the metal closes, and only when the record's is the one that ring
    # forces.
    inv = {v: k for k, v in enumerate(amap)}
    rgeo, dgeo = _geometries(r), _geometries(d)
    for (a, b), (cis_r, s1, s2) in rgeo.items():
        where = f"the double bond {r.GetAtomWithIdx(a).GetSymbol()}{a}={r.GetAtomWithIdx(b).GetSymbol()}{b}"
        key = tuple(sorted((amap[a], amap[b])))
        if key in dgeo:
            cis_d, t1, t2 = dgeo[key]
            if amap[a] != key[0]:
                t1, t2 = t2, t1
            if (cis_d ^ (t1 != amap[s1]) ^ (t2 != amap[s2])) != cis_r:
                out.append(f"{where}: the drawing's geometry is not the record's")
            continue
        ring = metal_ring(d, amap[a], amap[b], dm)
        if ring is None:
            out.append(f"{where}'s geometry is the record's but unmarked in the drawing, outside any ring of eight "
                       f"atoms or fewer that {metal} closes")
        else:
            # the ring's own neighbours of the two ends, in the record's atoms; where the ring reaches the metal
            # straight from an end (no bond in the record), the end's other neighbour stands opposite it
            flips, sides = 0, []
            for end, partner, nb in ((a, b, ring[1]), (b, a, ring[-2])):
                if inv[nb] in [x.GetIdx() for x in r.GetAtomWithIdx(end).GetNeighbors()]:
                    sides.append(inv[nb])
                    continue
                others = [x.GetIdx() for x in r.GetAtomWithIdx(end).GetNeighbors() if x.GetIdx() != partner]
                sides.append(others[0] if len(others) == 1 else None)
                flips += 1
            # the record's cis or trans, re-said about the ring's own neighbours: the ring forces cis
            if None in sides or not (cis_r ^ (s1 != sides[0]) ^ (s2 != sides[1]) ^ (flips % 2 == 1)):
                out.append(f"{where}: the record's geometry is not the one the ring {metal} closes forces")
    for key in dgeo:
        if tuple(sorted((inv[key[0]], inv[key[1]]))) not in rgeo:
            out.append(f"the drawing gives the double bond {key[0]}-{key[1]} a geometry the record does not")
    rs, ds = Chem.RWMol(rset), Chem.RWMol(match)
    for m_ in (rs, ds):
        for bd in m_.GetBonds():
            bd.SetStereo(Chem.BondStereo.STEREONONE)
            bd.SetBondDir(Chem.BondDir.NONE)
    # (d): every centre the record specifies is the drawing's; a centre it leaves open may be drawn only from the
    # reference, on the reference's own skeleton.
    unspecified = Chem.ChiralType.CHI_UNSPECIFIED
    extra = [amap[i] for i in range(rs.GetNumAtoms()) if rs.GetAtomWithIdx(i).GetChiralTag() == unspecified
             and ds.GetAtomWithIdx(amap[i]).GetChiralTag() != unspecified]
    for i in extra:
        ds.GetAtomWithIdx(i).SetChiralTag(unspecified)
    rs_m, ds_m = rs.GetMol(), ds.GetMol()
    for m_ in (rs_m, ds_m):
        Chem.AssignStereochemistry(m_, cleanIt=True, force=True)
    if Chem.MolToSmiles(ds_m) != Chem.MolToSmiles(rs_m):
        out.append(f"the drawing's stereocentres or double-bond geometry are not the record's {Chem.MolToSmiles(rs_m)}")
    if extra:
        if reference is None or not top:
            out.append(f"{len(extra)} stereocentre(s) the record leaves unspecified are drawn, and the entry names no "
                       "stereo_from")
        else:
            mine, theirs = skeleton_key(display, metal, top), skeleton_key(reference[0], metal, reference[1])
            if mine is None or theirs is None or mine != theirs:
                out.append(f"{len(extra)} stereocentre(s) the record leaves unspecified are drawn from the reference, "
                           "but the drawing's skeleton is not the reference's (stereo included)")
    # 3. the record's own bonds to the metal are kept
    for n in rn:
        if d.GetBondBetweenAtoms(amap[rm], amap[n]) is None:
            out.append(f"the record's own bond from {metal} to {r.GetAtomWithIdx(n).GetSymbol()} is missing")
    return out


def svg_key(smiles: str, width: int = 400, height: int = 300,
            recipe: str = RECIPE_VERSION) -> str:
    """Fingerprint of everything that decides what ``svg_for`` draws.

    Two records with the same key must get byte-identical SVGs, so a record whose key is
    unchanged since the last export can keep the SVG it already has instead of re-rendering
    it on a different platform and churning the snapshot.
    """
    payload = f"{recipe}|{width}x{height}|{smiles}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def atom_hex(atomic_num: int) -> str:
    """The colour an atom of this element is drawn in."""
    return CPK_HEX.get(atomic_num, FALLBACK_HEX)


# One element of the drawing that belongs to a single atom: its label glyphs or a radical dot.
# A bond's class names two atoms ('bond-3 atom-2 atom-4') and never matches. RDKit also classes
# its close-contact flag with an atom (a #FF0000 box round an atom the layout put too close to
# another, on 14 drawings: the large peptides, huperzine A, inulin, ivermectin). That box is not
# the atom's colour, so a repaint changes only the colours an older recipe drew the atom in.
_ATOM_TAG = re.compile(r"<(?:path|ellipse)\b[^>]*\bclass='atom-(\d+)'[^>]*>")
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")

# Element -> every colour an atom of it was drawn in, black (RDKit's colour for a radical dot)
# included; 0 to 118, the elements RDKit can draw.
_DRAWN_IN: dict[int, frozenset[str]] = {
    z: frozenset({"#000000", atom_hex(z)}
                 | {palette.get(z, unlisted) for palette, unlisted in RECOLOURABLE.values()})
    for z in range(119)}


def _paint(svg: str, mol) -> str:
    def fix(m: re.Match) -> str:
        idx = int(m.group(1))
        # An index past the parsed molecule is a hydrogen RDKit added to show stereo.
        z = mol.GetAtomWithIdx(idx).GetAtomicNum() if idx < mol.GetNumAtoms() else 1
        now = atom_hex(z).upper()                          # RDKit writes its colours in capitals
        return _HEX.sub(lambda h: now if h.group(0).lower() in _DRAWN_IN[z] else h.group(0),
                        m.group(0))
    return _ATOM_TAG.sub(fix, svg)


def recolour(svg: str, smiles: str) -> str:
    """Paint every atom label and dot of ``svg`` (drawn from ``smiles``) in its atom's colour now.

    An older recipe drew an atom in an older colour: black outside the ten-colour palette, or
    Jmol's untuned colour, or black for a radical dot, which RDKit always draws black. Only those
    colours change, so a drawing from a ``RECOLOURABLE`` recipe comes out exactly as this recipe
    would draw it on the machine that drew it (``svg_for`` ends with the same step).
    """
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    return _paint(svg, mol) if mol is not None else svg


def drawer(width: int = 400, height: int = 300, *, flag_close_contacts: bool = True,
           fixed_bond_px: float | None = None):
    """An RDKit SVG drawer with this recipe's options (the palette, one bond colour, no
    background). ``svg_for`` uses it as it is; the phase 5A recipes (``drawings``) turn off the
    close-contact box (a pure red #FF0000 that is no band colour) and may fix the bond length."""
    from rdkit.Chem.Draw import rdMolDraw2D

    d = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = d.drawOptions()
    palette = {z: _rgb01(hx) for z, hx in CPK_HEX.items()}
    palette[-1] = palette[0] = _rgb01(FALLBACK_HEX)    # unlisted element / dummy atom
    opts.updateAtomPalette(palette)
    opts.singleColourBonds = True                      # one bond color, not split half-by-atom
    opts.setSymbolColour((*_rgb01(CPK_HEX[6]), 1.0))   # bonds + carbon symbols = light blue-gray
    opts.clearBackground = False                       # transparent — sits on the dark panel
    if not flag_close_contacts:
        opts.flagCloseContactsDist = -1
    if fixed_bond_px:
        opts.fixedBondLength = fixed_bond_px
    return d


def draw(mol, width: int = 400, height: int = 300, **kw):
    """(svg, drawer) for ``mol`` as it is, its own 2D conformer kept if it has one."""
    d = drawer(width, height, **kw)
    d.DrawMolecule(mol)
    d.FinishDrawing()
    return _paint(d.GetDrawingText(), mol), d          # radical dots: RDKit draws them black


def svg_for(smiles: str, width: int = 400, height: int = 300) -> str | None:
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    return draw(mol, width, height)[0]
