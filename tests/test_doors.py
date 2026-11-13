"""The six doors (build plan everyday chemistry 2026-11, phase 4): sources/seeds/doors/*.yaml -> doors.json.

Two halves. The committed seeds against the committed snapshot: every reference resolves, every
requires holds, each stop's mark is the one its list's own seed holds, an in-place door keeps every
molecule its page lists, the groups are live (phase 7) with no interim, and doors.json is what the
compiler writes. Then the build stops when a fact fails: each kind of `requires:` broken on purpose
(the label drops the molecule, a quoted line changes, a pair loses its page, a formula moves), and
each house rule (a dash, an advice word, a completeness phrase, an LD50, the hangover wording, a
claim word with no entry).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from moleculefinder_etl.load import snapshot_export
from moleculefinder_etl.transform import claims, doors, relationships

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "snapshots"


def _inputs():
    mols = [json.loads(f.read_text()) for f in sorted((SNAP / "molecules").glob("*.json"))]
    cmp = json.loads((SNAP / "comparisons.json").read_text())
    prods = json.loads((SNAP / "products.json").read_text())["products"]
    pairs = json.loads((SNAP / "product_pairs.json").read_text())["pairs"]
    boards = {f.stem: json.loads(f.read_text()) for f in (SNAP / "leaderboards").glob("*.json") if f.stem != "index"}
    return mols, cmp, boards, prods, pairs


INPUTS = _inputs()
SEEDS = doors.load_seeds()


def _compile(mols=None, cmp=None, boards=None, prods=None, pairs=None, seeds=None):
    m, c, b, p, pp = (copy.deepcopy(x) for x in INPUTS)
    return doors.compile_doors(mols if mols is not None else m, cmp if cmp is not None else c,
                               boards if boards is not None else b, prods if prods is not None else p,
                               pairs if pairs is not None else pp, seeds=seeds if seeds is not None else copy.deepcopy(SEEDS))


COMPILED = _compile()
BY = {d["slug"]: d for d in COMPILED["doors"]}


def _fails(match: str, **kw):
    with pytest.raises(doors.DoorError) as e:
        _compile(**kw)
    assert match in str(e.value), str(e.value)
    return str(e.value)


# ── the committed seeds ──────────────────────────────────────────────────────
def test_the_six_doors_in_the_home_pages_order():
    assert [d["slug"] for d in COMPILED["doors"]] == list(doors.DOOR_ORDER)
    assert [d["order"] for d in COMPILED["doors"]] == [1, 2, 3, 4, 5, 6]
    assert [d["name"]["text"] for d in COMPILED["doors"]] == [
        "Coffee", "The medicine cabinet", "Bread", "Sugar and sweeteners", "Household cleaners", "Citrus"]


def test_all_six_doors_are_live_and_every_card_links_its_own_page():
    # Phase 7 (2026-11-13): the three group seeds are live: true with no interim, so each home card
    # follows the door to its own page (the web reads card.href and decides nothing).
    for slug in ("coffee", "bread", "citrus"):
        d = BY[slug]
        assert d["kind"] == "product" and d["live"] and d["interim"] is None
        assert d["card"]["href"] == f"/whats-in/{slug}"
    for slug in doors.GROUPS:
        d = BY[slug]
        assert d["kind"] == "group" and d["live"] and d["interim"] is None
        assert d["href"] == d["card"]["href"] == f"/whats-in/{slug}"
        assert "interim" not in SEEDS[slug]


def test_the_live_groups_are_no_product_record_and_join_the_ledger():
    # A group page renders from doors.json, never from products.json (so no molecule page lists it under
    # "Found in these products"), and once live its slug is in the products ledger, so a later removal
    # must answer 410 through the web's lib/gone.ts.
    prods = {p["slug"] for p in INPUTS[3]}
    ledger = json.loads((SNAP / "products_published.json").read_text())
    for slug in doors.GROUPS:
        assert slug not in prods
        assert slug in ledger["products"]
        assert not (SNAP / "molecules" / f"{slug}.json").exists()
        assert all(slug not in json.dumps(m.get("products") or []) for m in INPUTS[0])


def test_the_ledger_takes_a_live_group_and_never_a_dark_one():
    from moleculefinder_etl.transform import products_hold
    out = products_hold.published({"products": ["coffee"], "pairs": []}, [{"slug": "bread"}], [], COMPILED)
    assert set(doors.GROUPS) <= set(out["products"]) and {"coffee", "bread"} <= set(out["products"])
    dark = copy.deepcopy(COMPILED)
    for d in dark["doors"]:
        d["live"] = d["kind"] == "product"
    out = products_hold.published({"products": ["coffee"], "pairs": []}, [], [], dark)
    assert out["products"] == ["coffee"]
    assert products_hold.published(None, [], [], None)["products"] == []


def test_the_committed_doors_json_is_what_the_compiler_writes():
    assert json.loads((SNAP / "doors.json").read_text()) == COMPILED


def test_an_in_place_door_keeps_every_molecule_its_page_lists():
    prods = {p["slug"]: p for p in INPUTS[3]}
    for slug in ("coffee", "bread", "citrus"):
        listed = {r["slug"] for r in prods[slug]["molecules"]}
        assert listed <= set(BY[slug]["molecules"]), (slug, listed - set(BY[slug]["molecules"]))


def _marks(d):
    for s in d["stops"]:
        if s.get("molecule"):
            yield s["molecule"]["slug"], s.get("presence"), s.get("presence_list")
        for it in s["items"]:
            yield it["molecule"]["slug"], it["presence"], it["presence_list"]
        for r in s["more"]:
            if "aside" in r:
                yield r["aside"]["molecule"]["slug"], r["aside"]["presence"], r["aside"]["presence_list"]
    for a in d["also"]:
        yield a["molecule"]["slug"], a["presence"], a["presence_list"]


def test_every_mark_on_a_door_is_the_one_its_lists_own_seed_holds():
    mols = {m["slug"]: m for m in INPUTS[0]}
    prods = {p["slug"]: p for p in INPUTS[3]}
    n = 0
    for d in COMPILED["doors"]:
        for slug, presence, lst in _marks(d):
            if lst is None:
                assert presence is None
                continue
            if lst["kind"] == "product":
                want = next(r for r in prods[lst["slug"]]["molecules"] if r["slug"] == slug)["presence"]
            else:
                want = next(c for c in mols[slug]["categories"] if c["slug"] == lst["slug"])["presence"]
            assert presence == want and presence and presence["value"] in ("natural", "added", "body", "formed", "none")
            assert "inferred" not in json.dumps(presence)
            n += 1
    assert n > 60


def test_a_stop_with_no_mark_says_why_and_shows_none():
    unmarked = [(d["slug"], s["molecule"]["slug"]) for d in COMPILED["doors"] for s in d["stops"]
                if s.get("molecule") and s.get("presence") is None]
    assert unmarked == [("bread", "cellulose")]
    assert BY["bread"]["stops"][1]["presence_absent"]["text"].startswith("Not on our bread list")


def test_the_bread_chain_garrett_ruled_2026_11_10():
    """Re-ordered around what makes bread bread; maltodextrin only in starch's Read more."""
    b = BY["bread"]
    assert [s["molecule"]["slug"] if s.get("molecule") else s["nav"]["text"] for s in b["stops"]] == [
        "starch", "cellulose", "gluten", "ethanol", "The smell", "Also in the loaf"]
    gluten, ethanol = b["stops"][2], b["stops"][3]
    assert gluten["presence"]["value"] == "natural" and "trap gas and rise" in gluten["text"]["text"]
    assert (ethanol["presence"]["value"], ethanol["presence"]["formed_when"]) == ("formed", "fermentation")
    assert ethanol["presence"]["note"] == "Made by the yeast as the dough rises; most bakes off."
    starch_more = b["stops"][0]["more"]
    assert any(m.get("ref", {}).get("kind") == "answer" and m["ref"]["pair"] == "maltodextrin-vs-starch" for m in starch_more)
    assert any("maltodextrin-vs-starch" in json.dumps(link) for link in b["stops"][0]["links"])
    shown = {s["molecule"]["slug"] for s in b["stops"] if s.get("molecule")}
    assert "maltodextrin" not in shown
    assert [i["molecule"]["slug"] for i in b["stops"][5]["items"]] == [
        "sodium-chloride", "acrylamide", "thiamine", "niacin", "folic-acid", "iron"]


def test_theobromines_dog_fact_is_one_new_sentence_in_the_first_layer():
    stop = BY["coffee"]["stops"][2]
    assert stop["molecule"]["slug"] == "theobromine"
    assert stop["note"] == {"text": "Dogs clear theobromine far more slowly than people do, which is why chocolate is "
                                    "dangerous to them.", "new": True}
    assert ("coffee.stop3.note", stop["note"]["text"]) in doors.door_strings()
    assert sum(1 for d in COMPILED["doors"] for s in d["stops"] if s.get("note")) == 1


@pytest.mark.parametrize("bad, match", [
    ("Dogs clear theobromine slowly. Chocolate is dangerous to them.", "one sentence"),
    ("Dogs clear it slowly, its LD50 in dogs is 300 mg/kg.", "LD50"),
    ("Dogs.", "characters"),
])
def test_a_note_is_one_sentence_of_new_writing_under_the_house_rules(bad, match):
    seeds = copy.deepcopy(SEEDS)
    seeds["coffee"]["stops"][2]["note"] = bad
    _fails(match, seeds=seeds)


def test_garretts_line_fixes_2026_11_10_are_what_the_doors_quote():
    cmp = INPUTS[1]
    bic = cmp["sodium-bicarbonate-vs-sodium-carbonate"]["text"]
    assert "same two elements" not in bic
    assert bic.startswith("Baking soda and washing soda are both sodium salts of carbonic acid, NaHCO3 against Na2CO3: "
                          "washing soda has a second sodium where baking soda keeps a hydrogen, and that makes all the "
                          "difference to how alkaline they are.")
    lim = cmp["limonene-vs-linalool"]["text"]
    assert "whole of citrus peel oil" not in lim and "makes up most of citrus peel oil" in lim
    amm = cmp["ammonia-vs-sodium-hypochlorite"]["text"]
    assert ("Dissolved in water, ammonia is alkaline, which breaks up grease, and it evaporates completely, which is "
            "why it leaves glass without streaks.") in amm
    vit = {m["slug"]: m for m in INPUTS[0]}["ascorbic-acid"]
    assert "tart" not in vit["why_it_matters"]["text"] and "scurvy" in vit["why_it_matters"]["text"]
    assert vit["title"] == "Vitamin C" and 100 <= len(vit["description"]) <= 200
    quoted = json.dumps(COMPILED)
    assert "same two elements" not in quoted and "tart brightness" not in quoted
    clean = BY["household-cleaners"]
    assert any("Dissolved in water, ammonia is alkaline" in json.dumps(m) for m in clean["stops"][0]["more"])
    assert {m["slug"]: m for m in INPUTS[0]}["ammonia"]["what_it_does"]["sentences"][0]["text"].startswith(
        "Dissolved in water, ammonia is alkaline")


def test_the_mockups_coffee_chain():
    c = BY["coffee"]
    assert [s["nav"]["text"] for s in c["stops"]] == ["Caffeine", "Adenosine", "Theobromine", "Other drinks", "Also in the cup"]
    s1, s2, s3, s4, s5 = c["stops"]
    assert s1["presence"]["value"] == "natural" and s1["number"]["text"] == "about 95 mg per 8 oz cup"
    assert s2["presence"]["value"] == "body"
    assert s3["presence"]["value"] == "natural" and s3["number"]["list"]["slug"] == "chocolate"
    assert [(i["presence_list"]["slug"], i["presence"]["value"]) for i in s4["items"]] == [
        ("tea", "natural"), ("energy-drinks", "added"), ("soft-drinks", "added")]
    marks = {i["molecule"]["slug"]: (i["presence"]["value"], i["presence"].get("formed_when")) for i in s5["items"]}
    assert marks["caffeic-acid"] == ("natural", None) and marks["niacin"] == ("formed", "roasted")
    assert c["lede"]["text"].startswith("Follow caffeine, one of the 14 molecules on our coffee list")
    assert [w["to"]["href"] for w in c["where_next"]] == ["/whats-in/chocolate", "/vs/caffeine-vs-theobromine"]


def test_the_medicine_door_shows_the_labels_own_words_and_no_dosing():
    m = BY["medicine-cabinet"]
    assert [s["molecule"]["slug"] if s["molecule"] else [i["molecule"]["slug"] for i in s["items"]]
            for s in m["stops"]] == ["acetaminophen", "ibuprofen", "dextromethorphan", "doxylamine", ["menthol", "camphor"]]
    labels = [(r["product"], r["molecule"], r["purpose"], r["strength"]) for s in m["stops"] for r in s["labels"]]
    assert ("tylenol-extra-strength", "acetaminophen", "Pain reliever/fever reducer", "500 mg") in labels
    assert ("vicks-vaporub", "camphor", "Cough suppressant & topical analgesic", "4.8%") in labels
    text = json.dumps(m).lower()
    for word in ("overdose", "redose", "napqi", "liver", "every four", "a day"):
        assert word not in text, word


def test_titles_card_lines_and_descriptions_keep_their_lengths_and_are_unique():
    for d in COMPILED["doors"]:
        assert len(d["card"]["line"]["text"]) <= 130 and len(d["title"]["text"]) <= 60
        if d["kind"] == "group":
            assert len(d["page_title"]["text"]) <= 65 and 100 <= len(d["description"]["text"]) <= 160
    for field in ("title", "lede"):
        vals = [d[field]["text"] for d in COMPILED["doors"]]
        assert len(set(vals)) == 6
    descs = {m.get("description") for m in INPUTS[0]}
    for slug in doors.GROUPS:
        assert BY[slug]["description"]["text"] not in descs


def test_every_reference_is_pinned_and_every_link_resolves_to_a_page():
    body = json.dumps(COMPILED)
    assert '"pinned": false' in body          # the also lines only
    for d in COMPILED["doors"]:
        for s in d["stops"]:
            for r in s["more"]:
                if "text" in r and not r.get("new"):
                    assert r["ref"]["pinned"] is True
            for link in s["links"]:
                assert link["href"].startswith(("/m/", "/vs/", "/whats-in/", "/in/", "/best/", "/roam/"))


# ── the build stops when a fact fails (each requires broken on purpose) ──────
def test_a_label_that_drops_the_molecule_its_line_names_stops_the_build():
    prods = copy.deepcopy(INPUTS[3])
    nyq = next(p for p in prods if p["slug"] == "vicks-nyquil-intense-flu-liquicaps")
    nyq["molecules"] = [r for r in nyq["molecules"] if r["slug"] != "doxylamine"]
    msg = _fails("door medicine-cabinet", prods=prods)
    assert "no longer lists doxylamine" in msg and "requires lists" in msg


def test_a_label_that_gains_what_the_line_says_it_lacks_stops_the_build():
    prods = copy.deepcopy(INPUTS[3])
    day = next(p for p in prods if p["slug"] == "vicks-dayquil-severe-cold-and-flu")
    day["molecules"].append({"slug": "doxylamine", "role": "active", "title": "Doxylamine"})
    _fails("does not list doxylamine", prods=prods)


def test_a_list_that_drops_a_stop_molecule_stops_the_build():
    prods = copy.deepcopy(INPUTS[3])
    coffee = next(p for p in prods if p["slug"] == "coffee")
    coffee["molecules"] = [r for r in coffee["molecules"] if r["slug"] != "caffeine"]
    msg = _fails("door coffee", prods=prods)
    assert "no longer carries caffeine" in msg


def test_a_list_that_gains_a_molecule_the_door_does_not_show_stops_the_build():
    prods = copy.deepcopy(INPUTS[3])
    citrus = next(p for p in prods if p["slug"] == "citrus")
    citrus["molecules"].append({"slug": "ethylene", "role": "curated", "title": "Ethylene", "presence": {"value": "natural"}})
    _fails("which this door does not show", prods=prods)


def test_a_quoted_sentence_that_changes_stops_the_build():
    cmp = copy.deepcopy(INPUTS[1])
    cmp["adenosine-vs-caffeine"]["text"] = cmp["adenosine-vs-caffeine"]["text"].replace(
        "an afternoon crash actually is", "an afternoon slump is")
    msg = _fails("the quoted text is changed", cmp=cmp)
    assert "adenosine-vs-caffeine" in msg


def test_a_why_line_that_changes_stops_the_build():
    mols = copy.deepcopy(INPUTS[0])
    next(m for m in mols if m["slug"] == "ammonia")["why_it_matters"]["text"] += " Edited."
    _fails("why 'ammonia'", mols=mols)


def test_a_pair_that_loses_its_page_stops_the_build():
    cmp = copy.deepcopy(INPUTS[1])
    del cmp["starch-vs-cellulose"]
    _fails("starch-vs-cellulose", cmp=cmp)


def test_a_product_comparison_that_is_not_built_stops_the_build():
    _fails("advil-vs-tylenol-extra-strength", pairs=[])


def test_a_formula_that_moves_stops_the_build():
    mols = copy.deepcopy(INPUTS[0])
    next(m for m in mols if m["slug"] == "theobromine")["molecular_formula"] = "C7H8N4O3"
    _fails("requires formula_delta", mols=mols)


def test_a_sweetness_that_moves_stops_the_build():
    mols = copy.deepcopy(INPUTS[0])
    next(m for m in mols if m["slug"] == "stevioside")["relative_sweetness"] = 50
    _fails("sweetness_at_least", mols=mols)


def test_a_mark_that_leaves_the_list_stops_the_build():
    mols = copy.deepcopy(INPUTS[0])
    stev = next(m for m in mols if m["slug"] == "stevioside")
    stev["categories"] = [c for c in stev["categories"] if c["slug"] != "stevia"]
    _fails("the Stevia list no longer carries stevioside", mols=mols)


def test_a_group_under_the_three_molecule_gate_stops_the_build():
    seeds = copy.deepcopy(SEEDS)
    seeds["household-cleaners"]["stops"] = seeds["household-cleaners"]["stops"][:1] + [
        {"heading": "Ammonia again for the gate", "molecule": "ammonia", "mark": {"list": "household-cleaner"},
         "text": seeds["household-cleaners"]["stops"][0]["text"]}] * 2
    _fails("3-molecule gate", seeds=seeds)


# ── house rules on every string a door shows ─────────────────────────────────
@pytest.mark.parametrize("bad, match", [
    ("Coffee — opened", "dash"),
    ("Coffee, and how much you should drink", "advice"),
    ("Every molecule in coffee, explained", "completeness"),
    ("Coffee and caffeine's LD50 explained", "LD50"),
    ("Acetaldehyde and your hangover", "hangover"),
    ("Coffee, roughly 95 mg a cup", "advice or dosing"),
])
def test_a_house_rule_broken_in_new_writing_stops_the_build(bad, match):
    seeds = copy.deepcopy(SEEDS)
    seeds["coffee"]["stops"][0]["heading"] = bad
    _fails(match, seeds=seeds)


def test_a_claim_word_in_new_writing_needs_an_entry():
    lines = [("door", "coffee.title", "The most loved drink")]
    problems = claims.line_problems(lines, {})
    assert problems and "no entry" in problems[0]
    assert ("door", "coffee.title", "What's inside coffee?") in claims.corpus()


def test_the_lede_count_comes_from_the_data():
    prods = copy.deepcopy(INPUTS[3])
    coffee = next(p for p in prods if p["slug"] == "coffee")
    seeds = copy.deepcopy(SEEDS)
    seeds["coffee"]["also"] = seeds["coffee"]["also"][:-1]
    coffee["molecules"] = [r for r in coffee["molecules"] if r["slug"] != "acetaldehyde"]
    out = _compile(prods=prods, seeds=seeds)
    assert "one of the 13 molecules" in out["doors"][0]["lede"]["text"]


def test_a_live_door_with_an_interim_or_a_dark_door_without_one_stops_the_build():
    seeds = copy.deepcopy(SEEDS)
    seeds["medicine-cabinet"]["page"]["live"] = False
    _fails("a dark door names the existing page", seeds=seeds)
    seeds["medicine-cabinet"]["interim"] = {"hub": "pain-and-fever"}
    dark = _compile(seeds=seeds)["doors"][1]
    assert not dark["live"] and dark["card"]["href"] == "/in/pain-and-fever"
    seeds = copy.deepcopy(SEEDS)
    seeds["sugar-and-sweeteners"]["interim"] = {"hub": "tabletop-sweetener"}
    _fails("interim is for a dark door", seeds=seeds)
    seeds = copy.deepcopy(SEEDS)
    seeds["coffee"]["interim"] = {"hub": "coffee"}
    _fails("interim is for a dark door", seeds=seeds)


# ── what it does ─────────────────────────────────────────────────────────────
def test_what_it_does_compiles_and_reaches_only_the_molecules_with_an_entry():
    entries = doors.load_what_it_does()
    by = {m["slug"]: m for m in INPUTS[0]}
    with_field = {s for s, m in by.items() if "what_it_does" in m}
    assert with_field == set(entries)
    caf = by["caffeine"]["what_it_does"]
    assert caf["illustration"] == "receptor-block" and len(caf["sentences"]) == 3
    assert caf["sentences"][1]["text"].startswith("Caffeine happens to fit those same receptors")
    compiled = doors.compile_what_it_does(INPUTS[0], relationships.load_comparisons())
    assert {s: by[s]["what_it_does"] for s in with_field} == compiled


def test_what_it_does_refuses_a_changed_sentence_and_an_unknown_illustration():
    seed = relationships.load_comparisons()
    changed = copy.deepcopy(seed)
    changed["adenosine/caffeine"]["text"] = changed["adenosine/caffeine"]["text"].replace("closely enough", "well enough")
    with pytest.raises(doors.DoorError, match="new or changed"):
        doors.compile_what_it_does(INPUTS[0], changed)
    entries = doors.load_what_it_does()
    entries["caffeine"] = {**entries["caffeine"], "illustration": "a-drawing-of-caffeine"}
    with pytest.raises(doors.DoorError, match="illustration"):
        doors.compile_what_it_does(INPUTS[0], seed, entries)


# ── the export ───────────────────────────────────────────────────────────────
def test_the_export_writes_doors_json_and_removes_it_with_no_seeds(tmp_path, monkeypatch):
    from moleculefinder_etl.load import snapshot_guard
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    monkeypatch.setattr(snapshot_guard, "check", lambda *a, **k: None)
    recs = [{"cid": 1, "slug": "a", "title": "A", "synonyms": []}]
    snapshot_export.export(recs, {}, today="2026-11-10", doors={"doors": [{"slug": "coffee"}]})
    assert json.loads((tmp_path / "doors.json").read_text()) == {"doors": [{"slug": "coffee"}]}
    snapshot_export.export(recs, {}, today="2026-11-11")
    assert not (tmp_path / "doors.json").exists()
