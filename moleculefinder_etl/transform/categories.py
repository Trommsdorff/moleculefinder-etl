"""Categories & memberships: functional groups (SMARTS), curated foods/classes."""
from __future__ import annotations

# Minimal SMARTS set; extend as the canon grows.
FUNCTIONAL_GROUPS = {
    "alcohols": "[CX4][OX2H]",
    "carboxylic-acids": "[CX3](=O)[OX2H1]",
    "amines": "[NX3;H2,H1;!$(NC=O)]",
    "aromatics": "c1ccccc1",
    "ketones": "[#6][CX3](=O)[#6]",
}


def functional_groups(smiles: str) -> list[str]:
    """Return functional-group category slugs that match the molecule."""
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return []
    return [slug for slug, sm in FUNCTIONAL_GROUPS.items()
            if mol.HasSubstructMatch(Chem.MolFromSmarts(sm))]
