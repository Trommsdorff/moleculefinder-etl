"""Decide which interactive hooks a molecule gets, and their params.

See build plan section 7.1 for the flagship-vs-hand-crafted taxonomy this encodes.
"""
from __future__ import annotations

ETHANOL_CID = 702


def hooks_for(mol: dict) -> list[dict]:
    """Return `hook` rows for one assembled molecule dict.

    `mol` carries: cid, isomeric_smiles, half_life_hours, ld50 (list), curated (dict).
    """
    out: list[dict] = []
    curated = mol.get("curated") or {}

    # Flagship: still-in-your-system (any molecule with a half-life)
    if mol.get("half_life_hours"):
        out.append(_hook("still_in_system", "computed", {
            "half_life_hours": mol["half_life_hours"],
            "serving_mg": curated.get("serving_mg"),
        }))
    # Flagship: dose makes the poison. Fed by the SAME chosen row as the Deadliest
    # board (assemble._apply_best_oral_ld50 -> toxicity.best_oral): a preferred oral
    # value, never simply the first row parsed. A molecule with no usable oral row
    # gets no dose lens, because scaling an intravenous LD50 to a reader's body weight
    # and captioning it as a swallowed dose is the wrong answer, not a rough one.
    if mol.get("ld50_mg_per_kg") is not None:
        out.append(_hook("dose_poison", "inferred", {
            "ld50_mg_per_kg": mol["ld50_mg_per_kg"],
            "species": mol.get("ld50_species"),
            "route": mol.get("ld50_route"),
        }))
    # Hand-crafted interactive: BAC (ethanol only)
    if mol.get("cid") == ETHANOL_CID:
        out.append(_hook("bac", "computed", {}))
    # Curated-computed: scoville / sweetness
    if "capsaicinoid_ppm" in curated:
        out.append(_hook("scoville", "computed", {"ppm": curated["capsaicinoid_ppm"]}))
    if "relative_sweetness" in curated:
        out.append(_hook("sweetness", "from_source", {"x_sugar": curated["relative_sweetness"]}))
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
