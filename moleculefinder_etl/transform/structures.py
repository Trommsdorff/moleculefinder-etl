"""Build-time 2D SVG per molecule (crawlable, no-JS, instant first paint).

CPK-colored, palette-tuned for the dark Blueprint panel (Color System Brief §2a):
a uniform light-blue-gray skeleton with color reserved for heteroatom labels, on a
transparent background. Verified recipe for RDKit MolDraw2DSVG: updateAtomPalette
(carbon = key 6) + singleColourBonds + setSymbolColour(carbon) so bonds stay one
light color while N/O/S/... labels carry their element hue; clearBackground=False
so the SVG sits on the panel with no white box (the web CSS no longer inverts).
"""
from __future__ import annotations

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
