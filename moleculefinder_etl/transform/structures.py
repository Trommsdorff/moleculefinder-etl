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
``recolour`` paints any black left on an atom in that atom's colour.

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
import re

# The panel every drawing sits on, and the lightest of the surfaces that show one (the
# molecule page's stage is --bg-deep #09161e, the cards and the embed are darker or equal).
PANEL_HEX = "#0e2233"

# CPK atom colors as hex. Keys are atomic numbers.
# The first ten are the Color System Brief §2a hues, tuned for the dark panel. They are kept
# exactly as shipped so the 736 drawings that use only them do not change.
# Every other element is Jmol's CPK colour (jmol.sourceforge.net/jscolors, the standard
# table, 1 H to 109 Mt), so an element's colour keeps meaning something (Garrett's ruling,
# 2026-10-25; Color-as-Information). A Jmol colour under 3:1 against PANEL_HEX (WCAG, for a
# graphical object) is lightened by the minimum that reaches 3:1, raising only its HSL
# lightness so the hue and saturation stay; each one says so beside it.
# tests/test_structure_palette.py pins all of this.
CPK_HEX: dict[int, str] = {
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
    # Jmol CPK, by atomic number.
    2:   "#d9ffff",  # He
    3:   "#cc80ff",  # Li
    4:   "#c2ff00",  # Be
    5:   "#ffb5b5",  # B
    10:  "#b3e3f5",  # Ne
    11:  "#ab5cf2",  # Na
    12:  "#8aff00",  # Mg
    13:  "#bfa6a6",  # Al
    14:  "#f0c8a0",  # Si
    18:  "#80d1e3",  # Ar
    19:  "#9041d4",  # K   Jmol #8f40d4 2.97:1 -> 3.01:1, HSL lightness 54.1% -> 54.3%
    20:  "#3dff00",  # Ca
    21:  "#e6e6e6",  # Sc
    22:  "#bfc2c7",  # Ti
    23:  "#a6a6ab",  # V
    24:  "#8a99c7",  # Cr
    25:  "#9c7ac7",  # Mn
    26:  "#e06633",  # Fe
    27:  "#f090a0",  # Co
    28:  "#50d050",  # Ni
    29:  "#c88033",  # Cu
    30:  "#7d80b0",  # Zn
    31:  "#c28f8f",  # Ga
    32:  "#668f8f",  # Ge
    33:  "#bd80e3",  # As
    34:  "#ffa100",  # Se
    36:  "#5cb8d1",  # Kr
    37:  "#8c46cf",  # Rb  Jmol #702eb0 2.09:1 -> 3.00:1, HSL lightness 43.5% -> 54.3%
    38:  "#00ff00",  # Sr
    39:  "#94ffff",  # Y
    40:  "#94e0e0",  # Zr
    41:  "#73c2c9",  # Nb
    42:  "#54b5b5",  # Mo
    43:  "#3b9e9e",  # Tc
    44:  "#248f8f",  # Ru
    45:  "#0a7d8c",  # Rh
    46:  "#007493",  # Pd  Jmol #006985 2.59:1 -> 3.03:1, HSL lightness 26.1% -> 28.8%
    47:  "#c0c0c0",  # Ag
    48:  "#ffd98f",  # Cd
    49:  "#a67573",  # In
    50:  "#668080",  # Sn
    51:  "#9e63b5",  # Sb
    52:  "#d47a00",  # Te
    54:  "#429eb0",  # Xe
    55:  "#923adf",  # Cs  Jmol #57178f 1.49:1 -> 3.01:1, HSL lightness 32.5% -> 55.1%
    56:  "#00c900",  # Ba
    57:  "#70d4ff",  # La
    58:  "#ffffc7",  # Ce
    59:  "#d9ffc7",  # Pr
    60:  "#c7ffc7",  # Nd
    61:  "#a3ffc7",  # Pm
    62:  "#8fffc7",  # Sm
    63:  "#61ffc7",  # Eu
    64:  "#45ffc7",  # Gd
    65:  "#30ffc7",  # Tb
    66:  "#1fffc7",  # Dy
    67:  "#00ff9c",  # Ho
    68:  "#00e675",  # Er
    69:  "#00d452",  # Tm
    70:  "#00bf38",  # Yb
    71:  "#00ab24",  # Lu
    72:  "#4dc2ff",  # Hf
    73:  "#4da6ff",  # Ta
    74:  "#2194d6",  # W
    75:  "#267dab",  # Re
    76:  "#296fa3",  # Os  Jmol #266696 2.64:1 -> 3.01:1, HSL lightness 36.9% -> 40.0%
    77:  "#1e6eb0",  # Ir  Jmol #175487 2.05:1 -> 3.02:1, HSL lightness 31.0% -> 40.4%
    78:  "#d0d0e0",  # Pt
    79:  "#ffd123",  # Au
    80:  "#b8b8d0",  # Hg
    81:  "#a6544d",  # Tl
    82:  "#686a72",  # Pb  Jmol #575961 2.32:1 -> 3.01:1, HSL lightness 36.1% -> 42.7%
    83:  "#9e4fb5",  # Bi
    84:  "#ab5c00",  # Po
    85:  "#8d5f53",  # At  Jmol #754f45 2.29:1 -> 3.01:1, HSL lightness 36.5% -> 43.9%
    86:  "#428296",  # Rn
    87:  "#a200fa",  # Fr  Jmol #420066 1.10:1 -> 3.02:1, HSL lightness 20.0% -> 49.0%
    88:  "#007d00",  # Ra
    89:  "#70abfa",  # Ac
    90:  "#00baff",  # Th
    91:  "#00a1ff",  # Pa
    92:  "#008fff",  # U
    93:  "#0080ff",  # Np
    94:  "#006bff",  # Pu
    95:  "#545cf2",  # Am
    96:  "#785ce3",  # Cm
    97:  "#8a4fe3",  # Bk
    98:  "#a136d4",  # Cf
    99:  "#b31fd4",  # Es
    100: "#b51fbc",  # Fm  Jmol #b31fba 2.95:1 -> 3.00:1, HSL lightness 42.5% -> 42.9%
    101: "#be0eb1",  # Md  Jmol #b30da6 2.72:1 -> 3.00:1, HSL lightness 37.6% -> 40.0%
    102: "#c80e8f",  # No  Jmol #bd0d87 2.76:1 -> 3.02:1, HSL lightness 39.6% -> 42.0%
    103: "#d0006a",  # Lr  Jmol #c70066 2.79:1 -> 3.00:1, HSL lightness 39.0% -> 40.8%
    104: "#d2005b",  # Rf  Jmol #cc0059 2.87:1 -> 3.00:1, HSL lightness 40.0% -> 41.2%
    105: "#d40050",  # Db  Jmol #d1004f 2.95:1 -> 3.02:1, HSL lightness 41.0% -> 41.6%
    106: "#d90045",  # Sg
    107: "#e00038",  # Bh
    108: "#e6002e",  # Hs
    109: "#eb0026",  # Mt
}

# The one light colour for an atom the table does not list: elements 110-118 (Jmol stops at
# 109) and a dummy atom ("*"). RDKit's own defaults there are black (palette key -1) and near
# black (key 0), the very colours this palette exists to keep off the navy panel, so both keys
# point here. White, because no element in the table uses it (our hydrogen is #dbe9f2).
FALLBACK_HEX = "#ffffff"


# Bump when anything below changes the pixels: the palette, the draw options, the canvas.
# Every molecule redraws on the next run, which is the point.
RECIPE_VERSION = "2026-10-25.1"

# Earlier recipes whose drawings differ from this one ONLY in colour (same draw options, same
# canvas, a palette whose entries this one keeps). ``assemble._carried_svg`` repaints such a
# drawing with ``recolour`` instead of redrawing it, so a palette change moves no atom.
# 2026-09-07.1: the ten-colour palette; everything outside it, and every radical dot, black.
RECOLOURABLE: tuple[str, ...] = ("2026-09-07.1",)


def svg_key(smiles: str, width: int = 400, height: int = 300,
            recipe: str = RECIPE_VERSION) -> str:
    """Fingerprint of everything that decides what ``svg_for`` draws.

    Two records with the same key must get byte-identical SVGs, so a record whose key is
    unchanged since the last export can keep the SVG it already has instead of re-rendering
    it on a different platform and churning the snapshot.
    """
    payload = f"{recipe}|{width}x{height}|{smiles}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _rgb01(hex_str: str) -> tuple[float, float, float]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def atom_hex(atomic_num: int) -> str:
    """The colour an atom of this element is drawn in."""
    return CPK_HEX.get(atomic_num, FALLBACK_HEX)


# One element of the drawing that belongs to a single atom: its label glyphs or a radical dot.
# A bond's class names two atoms ('bond-3 atom-2 atom-4') and never matches.
_ATOM_TAG = re.compile(r"<(?:path|ellipse)\b[^>]*\bclass='atom-(\d+)'[^>]*>")
_BLACK = re.compile("#000000", re.IGNORECASE)


def _paint(svg: str, mol) -> str:
    def fix(m: re.Match) -> str:
        tag = m.group(0)
        if not _BLACK.search(tag):
            return tag
        idx = int(m.group(1))
        # An index past the parsed molecule is a hydrogen RDKit added to show stereo.
        z = mol.GetAtomWithIdx(idx).GetAtomicNum() if idx < mol.GetNumAtoms() else 1
        return _BLACK.sub(atom_hex(z).upper(), tag)   # RDKit writes its colours in capitals
    return _ATOM_TAG.sub(fix, svg)


def recolour(svg: str, smiles: str) -> str:
    """Paint every black atom element of ``svg`` (drawn from ``smiles``) in its atom's colour.

    Black on an atom means RDKit had no colour for it: a label outside an older palette, or a
    radical dot, which RDKit always draws black. Nothing else in the drawing is touched, so a
    drawing from a ``RECOLOURABLE`` recipe comes out exactly as this recipe would draw it on
    the machine that drew it (``svg_for`` ends with the same step).
    """
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    return _paint(svg, mol) if mol is not None else svg


def svg_for(smiles: str, width: int = 400, height: int = 300) -> str | None:
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None

    d = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = d.drawOptions()
    palette = {z: _rgb01(hx) for z, hx in CPK_HEX.items()}
    palette[-1] = palette[0] = _rgb01(FALLBACK_HEX)    # unlisted element / dummy atom
    opts.updateAtomPalette(palette)
    opts.singleColourBonds = True                      # one bond color, not split half-by-atom
    opts.setSymbolColour((*_rgb01(CPK_HEX[6]), 1.0))   # bonds + carbon symbols = light blue-gray
    opts.clearBackground = False                       # transparent — sits on the dark panel

    d.DrawMolecule(mol)
    d.FinishDrawing()
    return _paint(d.GetDrawingText(), mol)             # radical dots: RDKit draws them black
