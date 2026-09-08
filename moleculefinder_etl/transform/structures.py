"""Build-time 2D SVG per molecule (crawlable, no-JS, instant first paint).

CPK-colored, palette-tuned for the dark Blueprint panel (Color System Brief §2a):
a uniform light-blue-gray skeleton with color reserved for heteroatom labels, on a
transparent background. Verified recipe for RDKit MolDraw2DSVG: updateAtomPalette
(carbon = key 6) + singleColourBonds + setSymbolColour(carbon) so bonds stay one
light color while N/O/S/... labels carry their element hue; clearBackground=False
so the SVG sits on the panel with no white box (the web CSS no longer inverts).

**The rendered SVG is a stored artifact, not a re-derived one** (determinism, 2026-09-07).
RDKit's 2D depiction is deterministic for a given SMILES *on a given platform build*, but
for ~7% of the catalog (fused/bridged polycyclics, where the layout falls through to a
numerical minimiser) the macOS-arm64 and Linux-x86_64 wheels converge on different
coordinates. Measured: rdkit 2026.03.3 and 2026.03.6 on macOS agree on all 769 structures,
and both disagree with the Linux CI output on the same 53 — so the variable is the platform,
not the version, and pinning the version fixes nothing. Instead `svg_key()` fingerprints the
inputs and the caller reuses the previously exported SVG whenever the fingerprint matches, so
a molecule is drawn once and then carried forward byte-for-byte. Bump RECIPE_VERSION to force
a redraw of the whole catalog when the recipe below actually changes.
"""
from __future__ import annotations

import hashlib

# CPK atom colors as hex (Color System Brief §2a). Keys are atomic numbers.
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
}


# Bump when anything below changes the pixels: the palette, the draw options, the canvas.
# Every molecule redraws on the next run, which is the point.
RECIPE_VERSION = "2026-09-07.1"


def svg_key(smiles: str, width: int = 400, height: int = 300) -> str:
    """Fingerprint of everything that decides what ``svg_for`` draws.

    Two records with the same key must get byte-identical SVGs, so a record whose key is
    unchanged since the last export can keep the SVG it already has instead of re-rendering
    it on a different platform and churning the snapshot.
    """
    payload = f"{RECIPE_VERSION}|{width}x{height}|{smiles}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _rgb01(hex_str: str) -> tuple[float, float, float]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def svg_for(smiles: str, width: int = 400, height: int = 300) -> str | None:
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None

    d = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = d.drawOptions()
    opts.updateAtomPalette({z: _rgb01(hx) for z, hx in CPK_HEX.items()})
    opts.singleColourBonds = True                      # one bond color, not split half-by-atom
    opts.setSymbolColour((*_rgb01(CPK_HEX[6]), 1.0))   # bonds + carbon symbols = light blue-gray
    opts.clearBackground = False                       # transparent — sits on the dark panel

    d.DrawMolecule(mol)
    d.FinishDrawing()
    return d.GetDrawingText()
