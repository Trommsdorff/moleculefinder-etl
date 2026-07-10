"""Build-time 2D SVG per molecule (crawlable, no-JS, instant first paint)."""
from __future__ import annotations


def svg_for(smiles: str, width: int = 400, height: int = 300) -> str | None:
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    d = rdMolDraw2D.MolDraw2DSVG(width, height)
    d.DrawMolecule(mol)
    d.FinishDrawing()
    return d.GetDrawingText()
