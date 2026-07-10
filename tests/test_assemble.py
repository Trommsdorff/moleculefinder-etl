"""Per-molecule record assembly: hooks (§7.1), confidence routing, edges, filter-4."""
import math
import yaml
import pytest

from moleculefinder_etl.config import CURATED_DIR
from moleculefinder_etl.transform import assemble
from moleculefinder_etl.transform.confidence import FROM_SOURCE, COMPUTED, INFERRED
from moleculefinder_etl.sources.registry import BlockedSourceError
from tests.fixtures import (canon_row, fetched, CAFFEINE_PROPS, THEOBROMINE_PROPS, ETHANOL_PROPS)


def _curated(name):
    return yaml.safe_load((CURATED_DIR / f"{name}.yaml").read_text())


def _hooks_by_type(rec):
    return {h["type"]: h for h in rec["hooks"]}


def _caffeine():
    row = canon_row(2519, "Caffeine", qid="Q60235", tier="marquee",
                    summary="a central nervous system stimulant", pageviews=49284)
    f = fetched(CAFFEINE_PROPS, synonyms=["caffeine", "Guaranine", "1,3,7-Trimethylxanthine"],
                curated=_curated("caffeine"),
                toxicity=[{"endpoint": "LD50", "species": "mouse", "route": "oral",
                           "value_num": 127.0, "unit": "mg/kg", "confidence": FROM_SOURCE}],
                ghs={"signal_word": "Danger", "pictograms": ["GHS06"], "h_statements": ["H302"],
                     "confidence": FROM_SOURCE})
    return assemble.assemble_record(row, f, set())


# ── identity & structure ─────────────────────────────────────────────────────
def test_identity_and_structure():
    rec = _caffeine()
    assert rec["slug"] == "caffeine" and rec["title"] == "Caffeine" and rec["tier"] == "marquee"
    assert rec["molecular_weight"] == 194.19 and isinstance(rec["molecular_weight"], float)
    assert rec["isomeric_smiles"] and rec["structure_svg"].lstrip().startswith(("<?xml", "<svg"))
    assert rec["inchikey"] == "RYYVLZVUVIJVGH-UHFFFAOYSA-N"
    assert "curated" not in rec                     # internal overlay stripped from the record


# ── the caffeine still-in-your-system flagship (t½ ≈ 5 h) ────────────────────
def test_caffeine_half_life_hook_and_property():
    rec = _caffeine()
    sis = _hooks_by_type(rec)["still_in_system"]
    assert sis["params"]["half_life_hours"] == 5.0 and sis["params"]["serving_mg"] == 95
    assert sis["confidence"] == COMPUTED
    # the stored input that feeds the client decay curve, labeled as a curated fact
    hl = next(p for p in rec["properties"] if p["key"] == "half_life_hours")
    assert hl["value_num"] == 5.0 and hl["confidence"] == FROM_SOURCE
    # sanity on the model the web app will run: one half-life ⇒ half remains
    k = math.log(2) / sis["params"]["half_life_hours"]
    assert math.isclose(math.exp(-k * 5.0), 0.5, rel_tol=1e-9)


def test_dose_poison_prefers_curated_ld50():
    rec = _caffeine()
    dp = _hooks_by_type(rec)["dose_poison"]
    assert dp["confidence"] == INFERRED                 # rodent → human extrapolation
    assert dp["params"]["ld50_mg_per_kg"] == 192 and dp["params"]["species"] == "rat"
    assert rec["ld50_mg_per_kg"] == 192                 # curated value wins over the parsed 127
    assert rec["toxicity"][0]["value_num"] == 192       # prepended as the representative row


def test_structure_and_similar_hooks_present():
    types = set(_hooks_by_type(_caffeine()))
    assert {"structure", "similar"} <= types            # every molecule with a SMILES gets these


def test_food_category_from_curated():
    cats = {c["slug"]: c for c in _caffeine()["categories"]}
    assert "coffee" in cats and cats["coffee"]["kind"] == "food"
    assert cats["coffee"]["confidence"] == FROM_SOURCE


def test_editorial_content_block():
    blocks = _caffeine()["content_blocks"]
    assert any(b["block_type"] == "editorial" and "psychoactive" in b["body_md"] for b in blocks)


# ── confidence is routed through confidence.py for every value ───────────────
def test_confidence_labels_are_consistent():
    rec = _caffeine()
    assert rec["descriptors"]["confidence"] == FROM_SOURCE
    valid = {FROM_SOURCE, COMPUTED, INFERRED}
    for coll in ("hooks", "properties", "toxicity", "categories", "edges"):
        for item in rec[coll]:
            assert item["confidence"] in valid


def test_sources_never_blocked():
    rec = _caffeine()
    assert set(rec["sources"]) >= {"pubchem", "rdkit", "curated", "wikidata"}
    assert "foodb" not in rec["sources"] and "drugbank" not in rec["sources"]


def test_firewall_trips_on_blocked_source():
    assert assemble._src("pubchem") == "pubchem"
    with pytest.raises(BlockedSourceError):
        assemble._src("foodb")


# ── functional groups (computed from structure) ──────────────────────────────
def test_ethanol_functional_group():
    rec = assemble.assemble_record(canon_row(702, "Ethanol"), fetched(ETHANOL_PROPS), set())
    cats = {c["slug"]: c for c in rec["categories"]}
    assert "alcohols" in cats
    assert cats["alcohols"]["kind"] == "functional_group" and cats["alcohols"]["confidence"] == COMPUTED


def test_leaderboard_keys_present():
    caf = _caffeine()
    assert caf["molecular_weight"] == 194.19 and caf["ld50_mg_per_kg"] == 192
    asp = assemble.assemble_record(canon_row(134601, "Aspartame"),
                                   fetched({"CID": 134601, "SMILES": "CC(Cc1ccccc1)C(=O)O",
                                            "MolecularWeight": "294.30"}, curated=_curated("aspartame")), set())
    assert asp["relative_sweetness"] == 200


def test_curated_type_tags_and_direct_scoville():
    # Type tags fold into kind:"type" categories (caffeine → stimulant, methylxanthine).
    caf = _caffeine()
    type_cats = [c for c in caf["categories"] if c["kind"] == "type"]
    assert {"stimulant", "methylxanthine"} <= {c["slug"] for c in type_cats}
    assert all(c["confidence"] == FROM_SOURCE for c in type_cats)

    # Direct pure-compound Scoville for a non-capsaicinoid pungent molecule (piperine).
    pip = assemble.assemble_record(
        canon_row(638024, "Piperine"),
        fetched({"CID": 638024, "SMILES": "CCO", "MolecularWeight": "285.34"},
                curated=_curated("piperine")), set())
    assert pip["scoville_shu"] == 100000
    assert "pungent" in {c["slug"] for c in pip["categories"] if c["kind"] == "type"}

    # Capsaicin's pure-compound Scoville is 16M (capsaicinoid_ppm 1,000,000 × 16).
    cap = assemble.assemble_record(
        canon_row(1548943, "Capsaicin"),
        fetched({"CID": 1548943, "SMILES": "CCO", "MolecularWeight": "305.41"},
                curated=_curated("capsaicin")), set())
    assert cap["scoville_shu"] == 16000000


# ── slugs, edges, filter-4 ───────────────────────────────────────────────────
def test_unique_slugs_across_collisions():
    taken = set()
    a = assemble.assemble_record(canon_row(1, "Glucose"), fetched({"CID": 1, "SMILES": "OCC1OC(O)C(O)C(O)C1O", "MolecularWeight": "180.16"}), taken)
    b = assemble.assemble_record(canon_row(2, "Glucose"), fetched({"CID": 2, "SMILES": "OCC1OC(O)C(O)C(O)C1O", "MolecularWeight": "180.16"}), taken)
    assert a["slug"] == "glucose" and b["slug"] == "glucose-2"


def test_attach_edges_links_similar_molecules():
    caf = assemble.assemble_record(canon_row(2519, "Caffeine"), fetched(CAFFEINE_PROPS), set())
    theo = assemble.assemble_record(canon_row(5429, "Theobromine"), fetched(THEOBROMINE_PROPS), set())
    assemble.attach_edges([caf, theo])
    assert caf["edges"], "expected caffeine↔theobromine similarity edge"
    edge = caf["edges"][0]
    assert edge["neighbor_cid"] == 5429 and edge["neighbor_slug"] == "theobromine"
    assert 0.35 <= edge["tanimoto"] <= 1.0 and edge["confidence"] == COMPUTED
    assert edge["method"] == "morgan_r2_2048"


def test_synonyms_drop_registry_codes():
    syns = ["Guaranine", "RefChem:1055817", "SCHEMBL12345", "58-08-2", "1,3,7-Trimethylxanthine",
            "CHEBI:27732", "Theine"]
    cleaned = assemble._clean_synonyms(syns, "Caffeine")
    assert cleaned[0] == "Caffeine"
    assert "Guaranine" in cleaned and "Theine" in cleaned and "1,3,7-Trimethylxanthine" in cleaned
    assert not any(_is_code_leaked(s) for s in cleaned)


def _is_code_leaked(s):
    return ":" in s or s.startswith(("SCHEMBL", "RefChem", "CHEBI")) or s.replace("-", "").isdigit()


def test_filter4_demotes_orphans():
    good = assemble.assemble_record(canon_row(2519, "Caffeine"), fetched(CAFFEINE_PROPS), set())
    orphan = assemble.assemble_record(canon_row(999, "Mystery"), fetched({"CID": 999}), set())  # no SMILES
    kept, deferred = assemble.apply_filter4([good, orphan])
    assert [r["cid"] for r in kept] == [2519]
    assert [r["cid"] for r in deferred] == [999]
