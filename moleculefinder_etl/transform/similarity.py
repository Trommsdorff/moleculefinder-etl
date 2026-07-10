"""Structural similarity: Morgan fingerprints + Tanimoto, precomputed offline.

Kept deliberately portable (no Postgres cheminformatics cartridge). For ~10k
molecules an all-vs-all sweep is seconds; we store only the top-N edges.
"""
from __future__ import annotations
from typing import Iterable

from ..config import MORGAN_RADIUS, MORGAN_NBITS, SIMILARITY_TOP_N, SIMILARITY_FLOOR


def morgan_fingerprints(smiles_list: Iterable[str]):
    """Return (fingerprints, valid_index_map). Imports RDKit lazily."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    fps, index_map = [], []
    for i, smi in enumerate(smiles_list):
        mol = Chem.MolFromSmiles(smi) if smi else None
        if mol is None:
            continue
        fps.append(AllChem.GetMorganFingerprintAsBitVect(mol, MORGAN_RADIUS, nBits=MORGAN_NBITS))
        index_map.append(i)
    return fps, index_map


def top_edges(fps, index_map, top_n: int = SIMILARITY_TOP_N, floor: float = SIMILARITY_FLOOR):
    """Yield (i, j, tanimoto) edges (original indices) for the top-N neighbors."""
    from rdkit import DataStructs

    for local_i, fp in enumerate(fps):
        sims = DataStructs.BulkTanimotoSimilarity(fp, fps)
        ranked = sorted(enumerate(sims), key=lambda x: -x[1])
        kept = 0
        for local_j, score in ranked:
            if local_j == local_i:
                continue
            if score < floor or kept >= top_n:
                break
            yield index_map[local_i], index_map[local_j], round(float(score), 4)
            kept += 1
