"""Categories & memberships: functional groups (SMARTS), curated foods/classes."""
from __future__ import annotations

# Functional-group SMARTS. Each one becomes a computed kind:"functional_group"
# membership and therefore its own /in/<slug> hub, so the set is chosen for what a
# reader would recognize, not for exhaustive coverage of organic chemistry.
#
# The first five shipped from M1. The rest were added 2026-09 (build plan phase 3):
# they are the groups that most often name a smell, a taste or a hazard, and they
# cost nothing but a substructure match over data already in the snapshot.
FUNCTIONAL_GROUPS = {
    "alcohols": "[CX4][OX2H]",
    "carboxylic-acids": "[CX3](=O)[OX2H1]",
    "amines": "[NX3;H2,H1;!$(NC=O)]",
    "aromatics": "c1ccccc1",
    "ketones": "[#6][CX3](=O)[#6]",
    # H1 or H2 on the carbonyl carbon, so formaldehyde counts as an aldehyde too.
    "aldehydes": "[CX3;H1,H2]=[OX1]",
    "esters": "[CX3](=[OX1])[OX2H0][#6]",
    "amides": "[NX3][CX3](=[OX1])[#6]",
    # An aromatic hydroxyl. Distinct from "alcohols", which is the aliphatic case.
    "phenols": "[OX2H][c]",
    "thiols": "[#16X2H]",
    # Both oxygen neighbors must be non-carbonyl carbons, or every ester would also
    # read as an ether (the ester oxygen does bridge two carbons).
    "ethers": "[OD2]([#6;!$([#6]=[OX1])])[#6;!$([#6]=[OX1])]",
    "halogenated": "[F,Cl,Br,I]",
    "phosphates": "[PX4](=[OX1])([OX2,OX1-])[OX2,OX1-]",
}


def functional_groups(smiles: str) -> list[str]:
    """Return functional-group category slugs that match the molecule."""
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return []
    return [slug for slug, sm in FUNCTIONAL_GROUPS.items()
            if mol.HasSubstructMatch(Chem.MolFromSmarts(sm))]
