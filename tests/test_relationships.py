"""Everyday Worlds + Trails compiler (transform/relationships.py, build spec §2).

Two kinds of check: (1) the pure compile logic against a small synthetic molecule set,
and (2) the *real* curated inputs (worlds.yaml + relationships.csv) are well-formed and
house-rule compliant, independent of a generated snapshot.
"""
import pytest

from moleculefinder_etl.transform import relationships as rel
from moleculefinder_etl.transform.confidence import FROM_SOURCE, COMPUTED, INFERRED


# ── synthetic fixtures ────────────────────────────────────────────────────────
def _molecules():
    return [
        {"slug": "caffeine", "title": "Caffeine", "scope_bucket": "food-flavor", "family": "stimulant",
         "molecular_formula": "C8H10N4O2", "summary": "a stimulant",
         "edges": [{"neighbor_slug": "theobromine", "tanimoto": 0.62}]},
        {"slug": "theobromine", "title": "Theobromine", "scope_bucket": "plant-compound", "family": "stimulant",
         "edges": [{"neighbor_slug": "caffeine", "tanimoto": 0.62}]},
        {"slug": "adenosine", "title": "Adenosine", "scope_bucket": "body-endogenous", "family": None, "edges": []},
        {"slug": "paraxanthine", "title": "Paraxanthine", "scope_bucket": "body-endogenous", "family": None,
         "edges": []},
    ]


def _worlds():
    return [{
        "slug": "morning-coffee", "title": "Morning coffee", "blurb": "What's in your cup.",
        "tint": "food-flavor",
        "molecules": ["caffeine", "theobromine", "adenosine", "paraxanthine"],
        "journey": [{"slug": "caffeine", "caption": "in your cup"}, {"slug": "adenosine", "caption": "blocks"}],
    }]


def _rels():
    return [
        {"from_slug": "caffeine", "relation": "becomes", "to": "paraxanthine",
         "note": "major metabolite", "confidence": FROM_SOURCE},
        {"from_slug": "caffeine", "relation": "affects", "to": "adenosine",
         "note": "receptor antagonist", "confidence": INFERRED},
    ]


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(rel, "load_worlds", _worlds)
    monkeypatch.setattr(rel, "load_relationships", _rels)


# ── attach_trails ─────────────────────────────────────────────────────────────
def test_attach_trails_found_in_from_membership(patched):
    mols = _molecules()
    rel.attach_trails(mols)
    by = {m["slug"]: m for m in mols}
    # every member of the world gets a found_in edge to it, confidence from_source
    for s in ("caffeine", "theobromine", "adenosine", "paraxanthine"):
        fi = by[s]["trails"]["found_in"]
        assert [c["to"] for c in fi] == ["morning-coffee"]
        assert fi[0]["kind"] == "world" and fi[0]["title"] == "Morning coffee"
        assert fi[0]["confidence"] == FROM_SOURCE and fi[0]["tint"] == "food-flavor"


def test_attach_trails_affects_and_becomes(patched):
    mols = _molecules()
    rel.attach_trails(mols)
    caf = next(m for m in mols if m["slug"] == "caffeine")["trails"]
    becomes = caf["becomes"]
    assert [(c["to"], c["note"], c["confidence"]) for c in becomes] == [
        ("paraxanthine", "major metabolite", FROM_SOURCE)]
    assert becomes[0]["bucket"] == "body-endogenous" and becomes[0]["kind"] == "molecule"
    affects = caf["affects"]
    assert [(c["to"], c["note"], c["confidence"]) for c in affects] == [
        ("adenosine", "receptor antagonist", INFERRED)]     # affects is neutral + inferred


def test_related_is_not_stored_in_trails(patched):
    # "Related" (= resembles) is the record's existing computed `edges`; the web reads those
    # directly, so attach_trails must NOT duplicate them into trails (spec §6).
    mols = _molecules()
    rel.attach_trails(mols)
    assert set(mols[0]["trails"]) == {"found_in", "affects", "becomes"}


# ── build_worlds ──────────────────────────────────────────────────────────────
def test_build_worlds_index_and_detail(patched):
    payload = rel.build_worlds(_molecules())
    assert [w["slug"] for w in payload["worlds"]] == ["morning-coffee"]
    idx = payload["worlds"][0]
    assert idx["count"] == 4 and idx["tint"] == "food-flavor"
    assert idx["specks"] == ["food-flavor", "plant-compound", "body-endogenous", "body-endogenous"]

    detail = payload["detail"]["morning-coffee"]
    assert [n["slug"] for n in detail["molecules"]] == ["caffeine", "theobromine", "adenosine", "paraxanthine"]
    assert [(j["slug"], j["title"], j["caption"]) for j in detail["journey"]] == [
        ("caffeine", "Caffeine", "in your cup"), ("adenosine", "Adenosine", "blocks")]


def test_build_worlds_edges_carry_verbs_and_confidence(patched):
    detail = rel.build_worlds(_molecules())["detail"]["morning-coffee"]
    kinds = {(e["from"], e["to"], e["relation"]) for e in detail["edges"]}
    assert ("caffeine", "paraxanthine", "becomes") in kinds
    assert ("caffeine", "adenosine", "affects") in kinds
    # the computed resembles subset within the world (caffeine <-> theobromine), deduped
    resembles = [e for e in detail["edges"] if e["relation"] == "resembles"]
    assert len(resembles) == 1 and resembles[0]["confidence"] == COMPUTED
    assert set((resembles[0]["from"], resembles[0]["to"])) == {"caffeine", "theobromine"}
    for e in detail["edges"]:
        assert e["confidence"] in {FROM_SOURCE, COMPUTED, INFERRED}


# ── validation fails loudly on a dangling reference (spec §9) ──────────────────
def test_validate_raises_on_unknown_world_molecule(monkeypatch):
    monkeypatch.setattr(rel, "load_worlds", lambda: [{"slug": "w", "title": "W", "tint": "food-flavor",
                                                      "molecules": ["ghost"], "journey": []}])
    monkeypatch.setattr(rel, "load_relationships", lambda: [])
    with pytest.raises(SystemExit, match="unknown molecule 'ghost'"):
        rel.attach_trails(_molecules())


def test_validate_raises_on_affects_with_wrong_confidence(monkeypatch):
    # spec §2a: affects is always inferred. A curated affects row with any other confidence
    # must fail the build loudly, not slip into the snapshot (caught at build time, not just pytest).
    monkeypatch.setattr(rel, "load_worlds", _worlds)
    monkeypatch.setattr(rel, "load_relationships",
                        lambda: [{"from_slug": "caffeine", "relation": "affects", "to": "adenosine",
                                  "note": "receptor antagonist", "confidence": FROM_SOURCE}])
    with pytest.raises(SystemExit, match="must be confidence 'inferred'"):
        rel.attach_trails(_molecules())


def test_validate_raises_on_unknown_edge_target(monkeypatch):
    monkeypatch.setattr(rel, "load_worlds", _worlds)
    monkeypatch.setattr(rel, "load_relationships",
                        lambda: [{"from_slug": "caffeine", "relation": "becomes", "to": "ghost",
                                  "note": "x", "confidence": FROM_SOURCE}])
    with pytest.raises(SystemExit, match="unknown molecule 'ghost'"):
        rel.attach_trails(_molecules())


# ── the REAL curated inputs are well-formed + house-rule compliant ────────────
def test_real_worlds_yaml_is_well_formed():
    worlds = rel.load_worlds()
    assert len(worlds) == 10
    slugs = [w["slug"] for w in worlds]
    assert len(set(slugs)) == 10                                  # unique world slugs
    from moleculefinder_etl.transform.buckets import BUCKET_LABELS
    for w in worlds:
        assert w["title"] and w["blurb"] and w["molecules"]
        assert w["tint"] in BUCKET_LABELS                         # tint is a real bucket key
        members = set(w["molecules"])
        for j in w["journey"]:                                    # every journey step is a member
            assert j["slug"] in members, f"{w['slug']} journey step {j['slug']} not a member"


def test_real_relationships_csv_is_well_formed():
    rels = rel.load_relationships()
    assert rels, "expected curated relationships"
    for r in rels:
        assert r["relation"] in rel.CURATED_RELATIONS
        assert r["confidence"] in rel.VALID_CONFIDENCE
        assert r["from_slug"] and r["to"] and r["note"]
        if r["relation"] == "affects":
            assert r["confidence"] == INFERRED                    # affects is always inferred (spec §2a)


def test_no_em_dashes_in_visible_world_copy():
    # House rule: no em-dashes in visible site copy. Worlds power visible pages.
    for w in rel.load_worlds():
        blob = " ".join([w["title"], w["blurb"], *(j.get("caption", "") for j in w["journey"])])
        assert "—" not in blob and "–" not in blob
    for r in rel.load_relationships():
        assert "—" not in r["note"] and "–" not in r["note"]
