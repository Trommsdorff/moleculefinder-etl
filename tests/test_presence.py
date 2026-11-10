"""The presence field (build plan everyday chemistry 2026-11, phase 1).

Two halves: the rules on small fixtures (a missing or malformed mark stops the build, an unmarked
Wikidata row does not), and the real seeds and the committed snapshot (every curated entry is marked,
the vocabulary is closed, both directions carry one mark, nothing is inferred, the mockup's facts hold).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from moleculefinder_etl.transform import licence_gate, presence, products, relationships

SNAP = Path(__file__).resolve().parents[1] / "data" / "snapshots"
SEED = Path(__file__).resolve().parents[1] / "data" / "seed"


def _molecules() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((SNAP / "molecules").glob("*.json"))]


def _products() -> list[dict]:
    return json.loads((SNAP / "products.json").read_text())["products"]


def _write(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.write_text(text)
    return p


def _load(tmp: Path, food: str = "", product: str = "", worlds: str = "worlds: []\n",
          overlays: dict[str, str] | None = None, wikidata: str = "products: {}\n") -> dict:
    cdir = tmp / "curated"
    cdir.mkdir(exist_ok=True)
    for name, text in (overlays or {}).items():
        _write(cdir, name, text)
    return presence.load_marks(food_hubs=_write(tmp, "food_hubs.yaml", food),
                               product_hubs=_write(tmp, "product_hubs.yaml", product),
                               worlds=_write(tmp, "worlds.yaml", worlds), curated_dir=cdir,
                               wikidata=_write(tmp, "presence_wikidata.yaml", wikidata))


# ── the rules ────────────────────────────────────────────────────────────────
def test_a_well_formed_mark_of_each_value(tmp_path):
    marks = _load(tmp_path, food="""
coffee:
  molecules:
    - {slug: caffeine, presence: natural}
    - {slug: niacin, presence: formed, formed_when: roasted, presence_note: "From trigonelline."}
    - {slug: water, presence: added}
    - {slug: adenosine, presence: body}
    - {slug: methanol, presence: none, presence_note: "Released by enzymes."}
""")
    got = marks["food"]
    assert got[("coffee", "caffeine")] == {"value": "natural", "confidence": "from_source", "source": "curated"}
    assert got[("coffee", "niacin")]["formed_when"] == "roasted"
    assert presence.wording(got[("coffee", "niacin")]) == "Formed when roasted"
    assert presence.wording(got[("coffee", "water")]) == "Added by the maker"
    assert presence.wording(got[("coffee", "adenosine")]) == "Made by your body"
    assert presence.wording(got[("coffee", "methanol")]) == ""
    assert presence.wording(None) == "Not marked"


@pytest.mark.parametrize("entry,problem", [
    ("caffeine", "no presence mark"),
    ("{slug: caffeine}", "no presence mark"),
    ("{slug: caffeine, presence: inferred}", "is not one of"),
    ("{slug: caffeine, presence: formed}", "formed with no formed_when"),
    ("{slug: caffeine, presence: formed, formed_when: grilled}", "formed_when 'grilled' is not one of"),
    ("{slug: caffeine, presence: natural, formed_when: roasted}", "on a mark that is not formed"),
    ("{slug: caffeine, presence: none}", "none with no written reason"),
    ('{slug: caffeine, presence: none, presence_note: "Forms — here."}', "dash"),
    ('{slug: caffeine, presence: natural, presence_note: "Inferred from the class."}', "says inferred"),
])
def test_a_curated_entry_with_no_mark_or_a_bad_one_stops_the_build(tmp_path, entry, problem):
    with pytest.raises(presence.PresenceError) as e:
        _load(tmp_path, food=f"coffee:\n  molecules:\n    - {entry}\n")
    assert problem in str(e.value) and "coffee/caffeine" in str(e.value)


def test_every_problem_is_named_at_once(tmp_path):
    with pytest.raises(presence.PresenceError) as e:
        _load(tmp_path, food="coffee:\n  molecules:\n    - caffeine\n    - water\n",
              worlds="worlds:\n  - slug: w\n    molecules:\n      - adenosine\n")
    msg = str(e.value)
    assert "coffee/caffeine" in msg and "coffee/water" in msg and "w/adenosine" in msg


def test_an_overlay_row_and_a_hub_row_for_one_fact_must_agree(tmp_path):
    food = "coffee:\n  molecules:\n    - {slug: caffeine, presence: natural}\n"
    agree = {"caffeine.yaml": "slug: caffeine\nfoods:\n  - { category: coffee, presence: natural }\n"}
    assert _load(tmp_path, food=food, overlays=agree)["food"][("coffee", "caffeine")]["value"] == "natural"
    clash = {"caffeine.yaml": "slug: caffeine\nfoods:\n  - { category: coffee, presence: added }\n"}
    with pytest.raises(presence.PresenceError, match="one fact, one mark"):
        _load(tmp_path, food=food, overlays=clash)
    bare = {"caffeine.yaml": "slug: caffeine\nfoods:\n  - { category: coffee }\n"}
    with pytest.raises(presence.PresenceError, match="no presence mark"):
        _load(tmp_path, food=food, overlays=bare)


def test_a_curated_category_with_no_mark_stops_the_build():
    recs = [{"slug": "caffeine", "categories": [
        {"slug": "coffee", "kind": "food", "source": "curated"},
        {"slug": "stimulant", "kind": "type", "source": "curated"},       # not a list: never marked
        {"slug": "c-amide", "kind": "group", "source": "rdkit"}]}]
    marks = {"food": {("coffee", "caffeine"): {"value": "natural"}}, "product": {}, "world": {}, "wikidata": {}}
    assert presence.mark_categories(recs, marks) == 1
    assert recs[0]["categories"][0]["presence"] == {"value": "natural"}
    assert "presence" not in recs[0]["categories"][1] and "presence" not in recs[0]["categories"][2]
    with pytest.raises(presence.PresenceError, match="food tea/caffeine"):
        presence.mark_categories([{"slug": "caffeine", "categories": [
            {"slug": "tea", "kind": "food", "source": "curated"}]}], marks)


def _prods():
    return [
        {"slug": "advil", "source": {"type": "dailymed"}, "molecules": [
            {"slug": "ibuprofen", "role": "active"}, {"slug": "water", "role": "inactive"}]},
        {"slug": "pfas", "source": {"type": "class"}, "molecules": [{"slug": "pfoa", "role": "class"}]},
        {"slug": "coffee", "source": {"type": "curated", "hub": "coffee"}, "molecules": [
            {"slug": "caffeine", "role": "curated", "hub": "coffee"}]},
        {"slug": "chocolate", "source": {"type": "curated", "hub": "chocolate"},
         "also": [{"type": "world", "world": "chocolate"}, {"type": "wikidata", "qid": "Q195"}],
         "molecules": [{"slug": "tryptophan", "role": "world"}, {"slug": "copper", "role": "part", "property": "P527"}]},
        {"slug": "diet-pepsi", "source": {"type": "wikidata", "qid": "Q5275050"}, "molecules": [
            {"slug": "caffeine", "role": "part", "property": "P527"},
            {"slug": "aspartame", "role": "part", "property": "P527"}]},
    ]


_MARKS = {"food": {("coffee", "caffeine"): {"value": "natural"}}, "product": {},
          "world": {("chocolate", "tryptophan"): {"value": "natural"}},
          "wikidata": {("diet-pepsi", "caffeine"): {"value": "added"}, ("chocolate", "copper"): {"value": "natural"},
                       ("diet-pepsi", "gone"): {"value": "added"}}}


def test_labels_are_added_and_classes_none_by_rule_and_each_role_reads_its_seed():
    prods = _prods()
    unmarked = presence.mark_products(prods, _MARKS)
    advil, pfas, coffee, chocolate, pepsi = prods
    assert all(m["presence"]["value"] == "added" and m["presence"]["rule"] == "label" for m in advil["molecules"])
    assert pfas["molecules"][0]["presence"]["value"] == "none" and pfas["molecules"][0]["presence"]["note"]
    assert coffee["molecules"][0]["presence"] == {"value": "natural"}
    assert [m["presence"] for m in chocolate["molecules"]] == [{"value": "natural"}, {"value": "natural"}]
    assert pepsi["molecules"][0]["presence"] == {"value": "added"}
    # A Wikidata row with no mark is exported unmarked and listed, never an error.
    assert pepsi["molecules"][1]["presence"] is None
    assert unmarked == [{"product": "diet-pepsi", "molecule": "aspartame", "qid": "Q5275050", "property": "P527"}]


def test_a_curated_or_world_product_row_with_no_mark_stops_the_build():
    for prods in ([{"slug": "coffee", "source": {"type": "curated"}, "molecules": [
                      {"slug": "water", "role": "curated", "hub": "coffee"}]}],
                  [{"slug": "w", "source": {"type": "world", "world": "w"}, "molecules": [
                      {"slug": "geosmin", "role": "world"}]}]):
        with pytest.raises(presence.PresenceError, match="has no mark"):
            presence.mark_products(prods, _MARKS)


def test_the_unmarked_list_is_written(tmp_path):
    path = presence.write_unmarked([{"product": "p", "molecule": "m", "qid": "Q1", "property": "P527"}],
                                   tmp_path / "presence_unmarked.json")
    assert json.loads(path.read_text())[0]["molecule"] == "m"
    assert "presence_wikidata.yaml" in presence.unmarked_line({"product": "p", "molecule": "m"})


def test_attach_products_copies_the_mark_so_both_directions_are_one_fact():
    recs = [{"slug": "caffeine"}]
    prods = [{"slug": "coffee", "name": "Coffee", "kind": "drink",
              "molecules": [{"slug": "caffeine", "role": "curated", "presence": {"value": "natural"}}]}]
    products.attach_products(recs, prods)
    assert recs[0]["products"][0]["presence"] == {"value": "natural"}


def test_the_licence_gate_checks_the_marks_source():
    m = {"slug": "x", "categories": [{"slug": "coffee", "kind": "food", "source": "curated",
                                      "presence": {"value": "natural", "source": "nowhere"}}]}
    assert any("coffee.presence" in p for p in licence_gate.check_records([m]))
    m["categories"][0]["presence"]["source"] = "curated"
    assert licence_gate.check_records([m]) == []


def test_the_loaders_still_hand_out_slugs():
    assert all(isinstance(s, str) for w in relationships.load_worlds() for s in w["molecules"])
    for hubs in (relationships.load_food_hubs(), relationships.load_product_hubs()):
        assert all(isinstance(s, str) for h in hubs.values() for s in h["molecules"])
    assert relationships.load_food_hubs()["coffee"]["molecules"][0] == "caffeine"


# ── the real seeds and the committed snapshot ───────────────────────────────
def test_every_real_seed_entry_is_marked():
    marks = presence.load_marks()                  # raises, naming every problem, if one is not
    assert len(marks["food"]) >= 329 and len(marks["product"]) >= 83 and len(marks["world"]) >= 60
    for hub, entry in relationships.load_food_hubs().items():
        assert all((hub, s) in marks["food"] for s in entry["molecules"])
    for hub, entry in relationships.load_product_hubs().items():
        assert all((hub, s) in marks["product"] for s in entry["molecules"])
    for w in relationships.load_worlds():
        assert all((w["slug"], s) in marks["world"] for s in w["molecules"])


def test_every_curated_list_row_in_the_snapshot_is_marked_from_the_closed_list():
    rows = [c["presence"] for m in _molecules() for c in m.get("categories") or []
            if c["kind"] in ("food", "product") and c.get("source") == "curated"]
    rows += [m.get("presence") for p in _products() for m in p["molecules"] if m["role"] != "part"]
    assert rows and all(r is not None for r in rows)
    for r in rows:
        assert r["value"] in presence.VALUES
        assert ("formed_when" in r) == (r["value"] == "formed")
        if r["value"] == "formed":
            assert r["formed_when"] in presence.FORMED_WHEN
        if r["value"] == "none":
            assert r.get("note")
    # Every product molecule row carries the field; only a Wikidata row may be null (unmarked).
    assert all("presence" in m for p in _products() for m in p["molecules"])


def test_no_presence_value_carries_inferred():
    rows = [c.get("presence") for m in _molecules() for c in m.get("categories") or []]
    rows += [r.get("presence") for m in _molecules() for r in m.get("products") or []]
    rows += [m.get("presence") for p in _products() for m in p["molecules"]]
    rows = [r for r in rows if r]
    assert rows
    for r in rows:
        assert r["confidence"] == "from_source" and r["source"] == "curated"
        assert "inferred" not in json.dumps(r).lower()


def test_both_directions_carry_the_same_mark():
    by_slug = {m["slug"]: m for m in _molecules()}
    n = 0
    for p in _products():
        for pm in p["molecules"]:
            rows = [r for r in by_slug[pm["slug"]].get("products") or [] if r["slug"] == p["slug"]]
            assert len(rows) == 1 and rows[0]["presence"] == pm["presence"], (p["slug"], pm["slug"])
            n += 1
            # A curated product row and the molecule's membership in that hub are one fact too.
            if pm["role"] == "curated":
                cat = next(c for c in by_slug[pm["slug"]]["categories"]
                           if c["slug"] == pm["hub"] and c["kind"] == "food")
                assert cat["presence"] == pm["presence"], (p["slug"], pm["slug"])
    assert n > 2000


def test_the_mockups_facts_hold():
    prods = {p["slug"]: p for p in _products()}
    row = {(p, m["slug"]): m["presence"] for p in ("coffee", "morning-coffee") for m in prods[p]["molecules"]}
    assert row[("coffee", "caffeic-acid")]["value"] == "natural"
    assert presence.wording(row[("coffee", "niacin")]) == "Formed when roasted"
    assert presence.wording(row[("morning-coffee", "adenosine")]) == "Made by your body"
    assert row[("coffee", "caffeine")]["value"] == "natural"
    energy = {m["slug"]: m["presence"] for m in prods["energy-drinks"]["molecules"]}
    assert energy["caffeine"]["value"] == "added"


def test_the_committed_unmarked_list_matches_the_snapshot():
    listed = json.loads((SEED / "presence_unmarked.json").read_text())
    nulls = [{"product": p["slug"], "molecule": m["slug"]} for p in _products() for m in p["molecules"]
             if m.get("presence") is None]
    assert [{"product": u["product"], "molecule": u["molecule"]} for u in listed] == nulls
