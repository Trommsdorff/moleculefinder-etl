"""Decide which interactive hooks a molecule gets, and their params.

See build plan section 7.1 for the flagship-vs-hand-crafted taxonomy this encodes.
"""
from __future__ import annotations


def hooks_for(mol: dict) -> list[dict]:
    """Return `hook` rows for one assembled molecule dict.

    `mol` carries: cid, isomeric_smiles, curated (dict).
    """
    out: list[dict] = []
    curated = mol.get("curated") or {}

    # No still-in-the-system, dose or blood alcohol hook (phase 10 of the everyday chemistry plan,
    # Garrett's rulings of 2026-11-09): the calculators left the molecule page in phase 8 and the dose
    # lens answers 410. The half-life and typical serving stay as curated properties
    # (assemble._merge_curated), and the LD50 fields are untouched.

    # Curated-computed: scoville
    if "capsaicinoid_ppm" in curated:
        out.append(_hook("scoville", "computed", {"ppm": curated["capsaicinoid_ppm"]}))
    # The sweetness hook is attached with its value by relationships.attach_sweetness (sweetness.yaml).
    # Hand-crafted: smell card
    if "smell_card" in curated and curated["smell_card"]:
        out.append(_hook("smell_card", "from_source", curated["smell_card"]))
    # Canon-wide computed / utility (every molecule with a structure)
    if mol.get("isomeric_smiles"):
        out.append(_hook("structure", "from_source", {}))
        out.append(_hook("similar", "computed", {}))
    return out


def _hook(hook_type: str, confidence: str, params: dict) -> dict:
    return {"type": hook_type, "enabled": True, "confidence": confidence, "params": params}
