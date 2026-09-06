"""Guards for the 2026-09-05 traffic build plan (phases 1-3).

Each test pins a defect the plan was written to fix, so a future refactor that
reintroduces it fails here rather than on moleculefinder.com.
"""
from __future__ import annotations

import pytest

from moleculefinder_etl.transform import assemble, toxicity, leaderboards


# ── phase 2: the Deadliest board must rank an oral value or nothing ──────────
def test_best_oral_prefers_rat_then_mouse_then_any():
    rows = [
        {"species": "mouse", "route": "oral", "value_num": 10.0},
        {"species": "rat", "route": "oral", "value_num": 90.0},
        {"species": "dog", "route": "oral", "value_num": 5.0},
    ]
    assert toxicity.best_oral(rows)["species"] == "rat"
    assert toxicity.best_oral(rows[:1] + rows[2:])["species"] == "mouse"
    assert toxicity.best_oral([rows[2]])["species"] == "dog"


def test_best_oral_takes_the_lowest_within_the_preferred_species():
    rows = [{"species": "rat", "route": "oral", "value_num": 900.0},
            {"species": "rat", "route": "oral", "value_num": 90.0}]
    assert toxicity.best_oral(rows)["value_num"] == 90.0


def test_best_oral_never_returns_a_non_oral_row():
    """The stearic acid defect: an IV value ranked 3rd on a board that says oral."""
    rows = [{"species": "rat", "route": "iv", "value_num": 21.5},
            {"species": "mouse", "route": "other", "value_num": 57.0}]
    assert toxicity.best_oral(rows) is None


def test_best_oral_drops_an_implausible_sub_floor_value_unless_named():
    rows = [{"species": "rat", "route": "oral", "value_num": 0.8}]
    assert toxicity.best_oral(rows, "oxymetazoline") is None
    named = next(iter(toxicity.POTENT_TOXIN_SLUGS))
    assert toxicity.best_oral(rows, named)["value_num"] == 0.8


def test_deadliest_and_safest_are_the_same_population_read_both_ways():
    mols = [
        {"cid": 1, "slug": "a", "title": "A", "ld50_mg_per_kg": 10.0, "ld50_route": "oral",
         "ld50_species": "rat", "molecular_formula": "C"},
        {"cid": 2, "slug": "b", "title": "B", "ld50_mg_per_kg": 900.0, "ld50_route": "oral",
         "ld50_species": "rat", "molecular_formula": "C"},
    ]
    deadliest = leaderboards.rank("deadliest", mols)["entries"]
    safest = leaderboards.rank("safest", mols)["entries"]
    assert [e["slug"] for e in deadliest] == ["a", "b"]
    assert [e["slug"] for e in safest] == ["b", "a"]
    # both boards declare the route column, and it reaches the entry
    assert deadliest[0]["route"] == "oral" and deadliest[0]["species"] == "rat"


# ── phase 2: is_otc / dual_use must survive assembly ─────────────────────────
def test_assemble_record_carries_is_otc_and_dual_use_off_the_canon_row():
    rec = assemble.assemble_record(
        {"cid": 1983, "tier": "marquee", "enwiki_title": "Acetaminophen", "pageviews": 1,
         "is_otc": True, "dual_use": False},
        {"props": {"SMILES": "CC(=O)NC1=CC=C(C=C1)O", "MolecularFormula": "C8H9NO2",
                   "MolecularWeight": "151.16"},
         "synonyms": ["Acetaminophen"], "curated": None, "toxicity": [], "ghs": None},
        set())
    assert rec["is_otc"] is True and rec["dual_use"] is False


# ── phase 1: every record gets a unique description at or over the floor ─────
def _rec(**over):
    base = {"slug": "x", "title": "X", "molecular_formula": "C8H10N4O2",
            "molecular_weight": 194.19, "scope_family": "alkaloid",
            "scope_bucket": "food-flavor", "categories": [], "toxicity": [],
            "ghs": None, "synonyms": ["X", "Xine"], "edges": []}
    return {**base, **over}


def test_description_clears_the_floor_without_a_curated_line():
    d = assemble.build_description(_rec())
    assert len(d) >= assemble.MIN_DESCRIPTION
    assert d.startswith("X (C8H10N4O2, 194 g/mol) is a plant alkaloid found in everyday food")


def test_a_long_curated_line_stands_alone():
    line = "A" * 140
    d = assemble.build_description(_rec(why_it_matters={"text": line}))
    assert d == line + "."


def test_a_short_curated_line_is_completed_not_discarded():
    d = assemble.build_description(_rec(why_it_matters={"text": "Short line."}))
    assert d.startswith("Short line.")
    assert "C8H10N4O2" in d
    assert len(d) >= assemble.MIN_DESCRIPTION


def test_attach_descriptions_rejects_a_duplicate():
    a, b = _rec(slug="a", title="Same"), _rec(slug="b", title="Same")
    with pytest.raises(SystemExit, match="duplicate"):
        assemble.attach_descriptions([a, b])


def test_attach_descriptions_rejects_an_em_dash():
    r = _rec(why_it_matters={"text": "A curated line — with an em-dash " + "x" * 80})
    with pytest.raises(SystemExit, match="em-dash"):
        assemble.attach_descriptions([r])


# ── phase 3: one slug, one kind, and no one-molecule hub ─────────────────────
def test_unify_category_kinds_collapses_a_slug_onto_the_priority_kind():
    recs = [
        {"categories": [{"slug": "sugar", "kind": "family", "name": "Sugars"}]},
        {"categories": [{"slug": "sugar", "kind": "type", "name": "Sugar"}]},
    ]
    assemble.unify_category_kinds(recs)
    kinds = {c["kind"] for r in recs for c in r["categories"]}
    names = {c["name"] for r in recs for c in r["categories"]}
    assert kinds == {"family"} and names == {"Sugars"}


def test_prune_thin_categories_drops_a_derived_hub_but_never_a_curated_one():
    recs = [{"categories": [
        {"slug": "lonely", "kind": "element", "name": "Lonely"},
        {"slug": "stevia", "kind": "food", "name": "Stevia"},
    ]}]
    assemble.prune_thin_categories(recs, min_members=3)
    slugs = {c["slug"] for c in recs[0]["categories"]}
    assert slugs == {"stevia"}


def test_element_hubs_skip_carbon_hydrogen_and_oxygen():
    assert assemble._elements_in("C8H10N4O2") == ["N"]
    assert assemble._elements_in("ClNaO") == ["Cl", "Na"]   # two-letter symbols first


def test_family_hub_is_never_emitted_for_the_catch_all():
    rec = {"categories": [], "scope_bucket": None, "scope_family": None}
    assemble.apply_scope_bucket(rec, None, "other")
    assert not any(c["kind"] == "family" for c in rec["categories"])
    assemble.apply_scope_bucket(rec, None, "vitamin")
    assert [c["name"] for c in rec["categories"] if c["kind"] == "family"] == ["Vitamins"]
