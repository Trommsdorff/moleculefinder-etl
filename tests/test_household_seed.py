"""The household must-include seed + the hand-modeled (structureless) record path.

Covers the permanent fix for the traffic-ranking blind spots: force-included seed
molecules, and macromolecules (collagen, starch, gluten...) that have no single
PubChem compound and must render without a structure instead of crashing.
"""
from __future__ import annotations

from moleculefinder_etl.transform import canon, assemble


def test_household_seed_loads_and_resolves_cids():
    seed = canon.household_seed()
    assert len(seed) == 38, "seed should carry all 38 must-include molecules"

    hand = [m for m in seed if m["hand_model"]]
    addc = [m for m in seed if not m["hand_model"]]
    assert len(hand) == 18 and len(addc) == 20

    # add-core keep their real (positive) PubChem CID; hand-model get synthetic negatives.
    assert all(m["cid"] > 0 for m in addc)
    assert all(m["cid"] < 0 for m in hand)

    # synthetic CIDs are unique across the whole seed and never collide with real ones.
    cids = [m["cid"] for m in seed]
    assert len(cids) == len(set(cids)), "no CID collisions"


def test_synthetic_cid_is_stable_and_negative():
    a = canon._synthetic_cid("Collagen")
    b = canon._synthetic_cid("collagen")   # case/space-insensitive → same molecule
    assert a == b < 0


def test_assemble_handmodel_is_structureless_but_valid():
    row = {"cid": canon._synthetic_cid("Collagen"), "tier": "marquee",
           "enwiki_title": "Collagen", "pageviews": 51000, "summary": None,
           "hand_model": True}
    meta = {"name": "Collagen", "bucket": "body-endogenous", "family": "protein",
            "is_otc": False, "dual_use": False}
    rec = assemble.assemble_handmodel(row, meta, set())

    # identity present
    assert rec["title"] == "Collagen" and rec["slug"] == "collagen"
    # NO fabricated structure / descriptors
    assert rec["isomeric_smiles"] is None and rec["canonical_smiles"] is None
    assert rec["molecular_weight"] is None and rec["molecular_formula"] is None
    assert rec["structure_svg"] is None
    assert all(v is None for k, v in rec["descriptors"].items() if k != "confidence")
    # no numeric metrics ⇒ never on a leaderboard
    assert rec["ld50_mg_per_kg"] is None and rec["relative_sweetness"] is None
    # Scope B metadata + flags
    assert rec["scope_bucket"] == "body-endogenous" and rec["scope_family"] == "protein"
    assert rec["hand_model"] is True and rec["macromolecule"] is True
    # curated family becomes a kind:type membership (groups + survives filter-4)
    assert any(c["kind"] == "type" and c["slug"] == "protein" for c in rec["categories"])
    # every value is confidence-labeled (guardrail)
    assert rec["descriptors"]["confidence"]
    assert all(c.get("confidence") for c in rec["categories"])
    assert rec["sources"] == ["curated"]


def test_filter4_keeps_handmodel_and_edges_skip_it():
    hm = assemble.assemble_handmodel(
        {"cid": -7, "tier": "marquee", "enwiki_title": "Starch", "pageviews": 0, "summary": None},
        {"name": "Starch", "bucket": "food-flavor", "family": "polysaccharide"}, set())
    normal = {"cid": 2519, "slug": "caffeine", "title": "Caffeine", "isomeric_smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
              "family": None, "hooks": [], "edges": [], "categories": [{"slug": "x", "kind": "type"}]}
    records = [hm, normal]
    # attach_edges must not choke on the empty-SMILES structureless record
    assemble.attach_edges(records)
    assert hm["edges"] == []                       # no fingerprint ⇒ no neighbors
    kept, deferred = assemble.apply_filter4(records)
    assert hm in kept and hm not in deferred       # hand-model always kept


def test_assemble_record_has_uniform_scope_keys():
    # a normal record must also carry the new keys so the snapshot schema is uniform
    row = {"cid": 962, "tier": "marquee", "enwiki_title": "Water", "pageviews": 70000}
    rec = assemble.assemble_record(row, {"props": {}, "synonyms": [], "curated": None,
                                         "toxicity": [], "ghs": None}, set())
    for k in ("scope_bucket", "scope_family", "hand_model", "macromolecule"):
        assert k in rec
    assert rec["hand_model"] is False and rec["macromolecule"] is False


def test_build_canon_force_includes_seed(monkeypatch):
    """build_canon must union the seed in regardless of traffic/Wikidata (network stubbed)."""
    C = canon
    monkeypatch.setattr(C.pubchem, "name_to_cid", lambda name: None)   # no marquee name hits
    monkeypatch.setattr(C, "_notable_cached", lambda: [])              # empty notability net
    monkeypatch.setattr(C, "_pageviews_cached", lambda title: 0)
    monkeypatch.setattr(C, "_descriptions_cached", lambda cids: {})
    monkeypatch.setattr(C, "_curated_seed", lambda: {})

    rows = C.build_canon(target=1000)
    by_cid = {int(r["cid"]): r for r in rows}

    for m in C.household_seed():                       # every seed molecule survived
        assert m["cid"] in by_cid, f"{m['name']} dropped from canon"
        assert by_cid[m["cid"]]["tier"] == "marquee"   # marquee ⇒ never truncated

    assert 962 in by_cid and not by_cid[962].get("hand_model")        # Water: real add-core
    collagen = C._synthetic_cid("Collagen")
    assert collagen < 0 and by_cid[collagen].get("hand_model") is True  # macromolecule flagged


def test_parquet_roundtrips_hand_model_flag(tmp_path):
    rows = [
        {"cid": 962, "tier": "marquee", "build_order": 0, "has_common_name": True,
         "wikidata_qid": None, "enwiki_title": "Water", "summary": None, "pageviews": 70000},
        {"cid": -7, "tier": "marquee", "build_order": 1, "has_common_name": True,
         "wikidata_qid": None, "enwiki_title": "Starch", "summary": None, "pageviews": 0,
         "hand_model": True},
    ]
    p = canon.write_parquet(rows, tmp_path / "canon.parquet")
    back = canon.read_parquet(p)
    by_cid = {int(r["cid"]): r for r in back}
    assert bool(by_cid[-7]["hand_model"]) is True
    assert bool(by_cid[962]["hand_model"]) is False
