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
