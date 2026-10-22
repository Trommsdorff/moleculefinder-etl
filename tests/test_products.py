"""What's in it (growth plan run C1): product pages from labels, Wikidata and the worlds.

Pinned here:
* the label reader keeps exactly the structured facts the page uses (ingredients with their
  class, UNII and active moiety; the OTC purpose lines) and pairs a purpose with an active
  ingredient deterministically;
* the seed is fenced like every curated seed (every problem named at once);
* matching is by code only: a label ingredient by UNII (or its active moiety's), a Wikidata
  part by QID; a UNII two molecules share matches neither;
* the gate: a product page exists only with three or more molecules the catalog holds, and
  every product that fails is reported with its reason;
* the two directions are one fact: a molecule lists exactly the products that list it;
* the product inputs travel with the snapshot (the inputs manifest covers them, and a pinned
  build refuses a changed label like any other input);
* products.json is written by the export and removed when there is no seed.
"""
from __future__ import annotations

import json

import pytest

from moleculefinder_etl import inputs
from moleculefinder_etl.load import snapshot_export
from moleculefinder_etl.sources import dailymed, registry
from moleculefinder_etl.transform import products

SETID = "5d12e396-f82d-4c44-e063-6294a90ae291"
SETID2 = "fda754f6-d0f3-4dce-a17a-927d64f912f7"

# A synthetic SPL in the shape DailyMed serves (namespaced HL7 v3): two actives, one with a
# salt form whose active moiety is the molecule, inactives, a colour, a CNTM statement that is
# not an ingredient, and the OTC active/purpose sections as a two-column table.
SPL = b"""<?xml version="1.0" encoding="UTF-8"?>
<document xmlns="urn:hl7-org:v3">
  <code code="34390-5" codeSystem="2.16.840.1.113883.6.1" displayName="HUMAN OTC DRUG LABEL"/>
  <title>Example Cold Caplets</title>
  <effectiveTime value="20260818"/>
  <versionNumber value="4"/>
  <author><assignedEntity><representedOrganization><name>Example Brands LLC</name>
  </representedOrganization></assignedEntity></author>
  <component><structuredBody>
    <component><section>
      <subject><manufacturedProduct><manufacturedProduct>
        <name>Example Cold</name>
        <ingredient classCode="ACTIB"><ingredientSubstance>
          <code code="362O9ITL9D" codeSystem="2.16.840.1.113883.4.9"/><name>ACETAMINOPHEN</name>
          <activeMoiety><activeMoiety><code code="362O9ITL9D" codeSystem="2.16.840.1.113883.4.9"/>
          <name>ACETAMINOPHEN</name></activeMoiety></activeMoiety>
        </ingredientSubstance></ingredient>
        <ingredient classCode="ACTIB"><ingredientSubstance>
          <code code="9D2RTI9KYH" codeSystem="2.16.840.1.113883.4.9"/><name>DEXTROMETHORPHAN HYDROBROMIDE</name>
          <activeMoiety><activeMoiety><code code="7355X3ROTS" codeSystem="2.16.840.1.113883.4.9"/>
          <name>DEXTROMETHORPHAN</name></activeMoiety></activeMoiety>
        </ingredientSubstance></ingredient>
        <ingredient classCode="IACT"><ingredientSubstance>
          <code code="70097M6I30" codeSystem="2.16.840.1.113883.4.9"/><name>MAGNESIUM STEARATE</name>
        </ingredientSubstance></ingredient>
        <ingredient classCode="IACT"><ingredientSubstance>
          <code code="OP1R32D61U" codeSystem="2.16.840.1.113883.4.9"/><name>MICROCRYSTALLINE CELLULOSE</name>
        </ingredientSubstance></ingredient>
        <ingredient classCode="COLR"><ingredientSubstance>
          <code code="WZB9127XOA" codeSystem="2.16.840.1.113883.4.9"/><name>FD&amp;C RED NO. 40</name>
        </ingredientSubstance></ingredient>
        <ingredient classCode="CNTM"><ingredientSubstance>
          <code code="2M83C4R6ZB" codeSystem="2.16.840.1.113883.4.9"/><name>PEANUT</name>
        </ingredientSubstance></ingredient>
      </manufacturedProduct></manufacturedProduct></subject>
    </section></component>
    <component><section>
      <code code="55106-9" codeSystem="2.16.840.1.113883.6.1" displayName="OTC - ACTIVE INGREDIENT SECTION"/>
      <text><paragraph>&#8203;Active ingredients (in each caplet)</paragraph></text>
      <component><section>
        <code code="55105-1" codeSystem="2.16.840.1.113883.6.1" displayName="OTC - PURPOSE SECTION"/>
        <text><table><tbody>
          <tr><td>Active ingredients (in each caplet)</td><td>Purpose</td></tr>
          <tr><td>Acetaminophen 500 mg</td><td>PAIN RELIEVER/FEVER REDUCER</td></tr>
          <tr><td>Dextromethorphan HBr 15 mg</td><td>Cough suppressant</td></tr>
        </tbody></table></text>
      </section></component>
    </section></component>
  </structuredBody></component>
</document>
"""


# ── the label reader ─────────────────────────────────────────────────────────
def test_parse_keeps_the_ingredient_list_with_class_unii_and_moiety():
    spl = dailymed.parse(SPL, SETID)
    assert spl["labeler"] == "Example Brands LLC"
    assert spl["doc_type"] == "HUMAN OTC DRUG LABEL"
    assert spl["version"] == 4 and spl["effective"] == "20260818"
    assert [(i["role"], i["name"], i["unii"], i["moiety"]) for i in spl["ingredients"]] == [
        ("active", "ACETAMINOPHEN", "362O9ITL9D", []),
        ("active", "DEXTROMETHORPHAN HYDROBROMIDE", "9D2RTI9KYH", ["7355X3ROTS"]),
        ("inactive", "MAGNESIUM STEARATE", "70097M6I30", []),
        ("inactive", "MICROCRYSTALLINE CELLULOSE", "OP1R32D61U", []),
        ("inactive", "FD&C RED NO. 40", "WZB9127XOA", []),
    ]                                          # the CNTM "contains" statement is not an ingredient


def test_purposes_from_a_table_and_sentence_case():
    spl = dailymed.parse(SPL, SETID)
    assert dailymed.purposes(spl) == {"ACETAMINOPHEN": "Pain reliever/fever reducer",
                                      "DEXTROMETHORPHAN HYDROBROMIDE": "Cough suppressant"}


def test_purposes_paired_by_position_and_a_single_purpose_for_all():
    spl = {"doc_type": "HUMAN OTC DRUG LABEL", "ingredients": [{"role": "active", "name": "ACETAMINOPHEN"},
                           {"role": "active", "name": "DOXYLAMINE SUCCINATE"}],
           "active_lines": ["Active ingredients (in each caplet)", "Acetaminophen 325 mg",
                            "Doxylamine succinate 6.25 mg", "*footnote"],
           "purpose_lines": ["Purpose", "Pain reliever", "Antihistamine"], "purpose_rows": []}
    assert dailymed.purposes(spl) == {"ACETAMINOPHEN": "Pain reliever", "DOXYLAMINE SUCCINATE": "Antihistamine"}
    one = {"ingredients": [{"role": "active", "name": "MENTHOL"}, {"role": "active", "name": "THYMOL"}],
           "active_lines": ["Menthol 0.042%"], "purpose_lines": ["Antiplaque/antigingivitis"], "purpose_rows": []}
    assert dailymed.purposes(one) == {"MENTHOL": "Antiplaque/antigingivitis", "THYMOL": "Antiplaque/antigingivitis"}


def test_no_purpose_when_the_label_does_not_pair_them():
    spl = {"doc_type": "HUMAN OTC DRUG LABEL", "ingredients": [{"role": "active", "name": "ASPIRIN"}, {"role": "active", "name": "CAFFEINE"}],
           "active_lines": ["Aspirin 250 mg"], "purpose_lines": ["Pain reliever", "Pain reliever aid", "Extra"],
           "purpose_rows": []}
    assert dailymed.purposes(spl) == {}


@pytest.mark.parametrize("text,want", [
    ("PAIN RELIEVER", "Pain reliever"), ("• Antihistamine.", "Antihistamine"),
    ("Purposes", None), ("Acetaminophen 500 mg", None), ("x" * 61, None),
    ("Skin protectant — sunscreen", "Skin protectant ,  sunscreen".replace(" ,  ", ", ")),
])
def test_clean_purpose(text, want):
    assert dailymed.clean_purpose(text) == want


def test_fetch_refuses_anything_but_a_set_id():
    with pytest.raises(ValueError):
        dailymed.fetch("../etc/passwd")


def test_open_food_facts_is_blocked_and_dailymed_is_registered():
    with pytest.raises(registry.BlockedSourceError):
        registry.assert_not_blocked("openfoodfacts")
    registry.assert_not_blocked("dailymed")
    assert registry.SOURCES["dailymed"]["license"] == "US Government Public Domain"


# ── the seed ─────────────────────────────────────────────────────────────────
WORLDS = [{"slug": "morning-coffee", "title": "Morning coffee", "blurb": "What's in your cup.",
           "molecules": ["m1", "m2", "m3", "m4"], "journey": [{"slug": "m1", "caption": "in your cup"}]}]


def _seed(tmp_path, rows):
    p = tmp_path / "products.yaml"
    p.write_text(json.dumps({"products": rows}))
    return products.load_seed(p, WORLDS)


def test_seed_reads_the_three_source_kinds(tmp_path):
    rows = _seed(tmp_path, [
        {"slug": "example-cold", "name": "Example Cold", "kind": "medicine", "dailymed": SETID},
        {"slug": "diet-cola", "name": "Diet cola", "kind": "drink", "wikidata": "Q5275050"},
        {"slug": "morning-coffee", "name": "Morning coffee", "kind": "drink", "world": "morning-coffee"},
    ])
    assert [(r["slug"], r["source"], r["item"]) for r in rows] == [
        ("example-cold", "dailymed", SETID), ("diet-cola", "wikidata", "Q5275050"),
        ("morning-coffee", "world", "morning-coffee")]


def test_seed_names_every_problem_at_once(tmp_path):
    with pytest.raises(products.ProductSeedError) as err:
        _seed(tmp_path, [
            {"slug": "Bad Slug", "name": "x", "kind": "medicine", "dailymed": SETID},
            {"slug": "dup", "name": "A — B", "kind": "medicine", "dailymed": SETID2},
            {"slug": "dup", "name": "x", "kind": "gadget", "wikidata": "Q1"},
            {"slug": "two", "name": "x", "kind": "food", "wikidata": "Q2", "world": "morning-coffee"},
            {"slug": "nope", "name": "x", "kind": "food", "world": "no-such-world"},
            {"slug": "badid", "name": "x", "kind": "food", "dailymed": "not-a-set-id"},
            {"slug": "again", "name": "x", "kind": "medicine", "dailymed": SETID},
            {"slug": "extra", "name": "x", "kind": "food", "wikidata": "Q3", "logo": "y"},
        ])
    msg = str(err.value)
    for want in ("lowercase words", "slug used twice", "em or en dash", "kind must be one of",
                 "exactly one of", "no world 'no-such-world'", "not a DailyMed set id",
                 "same dailymed item", "unknown field(s) logo"):
        assert want in msg, want


def test_the_committed_seed_is_valid():
    seed = products.load_seed()
    assert seed, "products.yaml is empty"
    assert {p["kind"] for p in seed} <= set(products.KINDS)
    worlds = [p for p in seed if p["source"] == "world"]
    assert len(worlds) == 10                    # the ten everyday worlds are the first ten


# ── compile: matching and the gate ────────────────────────────────────────────
def _rec(slug, cid, qid=None, title=None):
    return {"slug": slug, "cid": cid, "title": title or slug.title(), "wikidata_qid": qid}


RECORDS = [
    _rec("acetaminophen", 1983, "Q57055"), _rec("dextromethorphan", 5360696, "Q422239"),
    _rec("magnesium-stearate", 11177, "Q416423"), _rec("allura-red-ac", 33258, "Q414484"),
    _rec("caffeine", 2519, "Q60235"), _rec("water", 962, "Q283"),
    _rec("estradiol", 5757), _rec("estradiol-medication", 9999999),
    _rec("m1", 1), _rec("m2", 2), _rec("m3", 3), _rec("m4", 4),
]
UNIIS = {1983: ["362O9ITL9D"], 5360696: ["7355X3ROTS"], 11177: ["70097M6I30"], 33258: ["WZB9127XOA"],
         2519: ["3G6A5W338E"], 962: ["059QF0KO0R"], 5757: ["4TI98Z838E"], 9999999: ["4TI98Z838E"]}


def _compile(seed, labels=None, parts=None):
    labels = labels or {}
    return products.compile_products(RECORDS, seed, spl=lambda s: labels.get(s), parts=parts or {},
                                     uniis=UNIIS, worlds=WORLDS)


def _p(slug, kind, source, item, name=None):
    return {"slug": slug, "name": name or slug, "kind": kind, "source": source, "item": item}


def test_a_label_matches_by_unii_then_moiety_actives_first_with_purposes():
    passed, report = _compile([_p("example-cold", "medicine", "dailymed", SETID)],
                              {SETID: dailymed.parse(SPL, SETID)})
    assert report["passed"] == 1 and report["failed"] == 0
    mols = passed[0]["molecules"]
    assert [(m["slug"], m["role"], m["match"]) for m in mols] == [
        ("acetaminophen", "active", "unii"), ("dextromethorphan", "active", "moiety"),
        ("magnesium-stearate", "inactive", "unii"), ("allura-red-ac", "inactive", "unii")]
    assert mols[0]["purpose"] == "Pain reliever/fever reducer"
    assert "purpose" not in mols[2]
    assert passed[0]["listed"] == 5 and passed[0]["not_in_catalog"] == 1
    assert passed[0]["actives_not_in_catalog"] == []
    assert passed[0]["source"]["url"].endswith(SETID)
    assert report["label_ingredients_not_in_catalog"] == [{"name": "MICROCRYSTALLINE CELLULOSE", "labels": 1}]


def test_an_animal_label_fails_the_gate_and_an_unmatched_active_is_named():
    spl = {"doc_type": "OTC ANIMAL DRUG LABEL", "ingredients": [], "active_lines": [], "purpose_lines": [],
           "purpose_rows": []}
    passed, report = _compile([_p("x", "household", "dailymed", SETID)], {SETID: spl})
    assert passed == [] and report["failures"][0]["reason"].startswith("not a label for people")
    spl = {"doc_type": "HUMAN OTC DRUG LABEL",
           "ingredients": [{"role": "active", "name": "MENTHOL, UNSPECIFIED FORM", "unii": "L7T10EIP3A", "moiety": []},
                           {"role": "inactive", "name": "WATER", "unii": "059QF0KO0R", "moiety": []},
                           {"role": "inactive", "name": "CAFFEINE", "unii": "3G6A5W338E", "moiety": []},
                           {"role": "inactive", "name": "MAGNESIUM STEARATE", "unii": "70097M6I30", "moiety": []}],
           "active_lines": [], "purpose_lines": [], "purpose_rows": []}
    passed, _ = _compile([_p("x", "medicine", "dailymed", SETID)], {SETID: spl})
    assert passed[0]["actives_not_in_catalog"] == ["MENTHOL, UNSPECIFIED FORM"]


def test_an_active_listed_again_as_inactive_stays_active_once():
    spl = {"doc_type": "HUMAN OTC DRUG LABEL", "ingredients": [{"role": "inactive", "name": "CAFFEINE", "unii": "3G6A5W338E", "moiety": []},
                           {"role": "active", "name": "CAFFEINE", "unii": "3G6A5W338E", "moiety": []},
                           {"role": "inactive", "name": "WATER", "unii": "059QF0KO0R", "moiety": []},
                           {"role": "inactive", "name": "MAGNESIUM STEARATE", "unii": "70097M6I30", "moiety": []}],
           "active_lines": [], "purpose_lines": [], "purpose_rows": []}
    passed, _ = _compile([_p("x", "medicine", "dailymed", SETID)], {SETID: spl})
    assert [(m["slug"], m["role"]) for m in passed[0]["molecules"]] == [
        ("caffeine", "active"), ("water", "inactive"), ("magnesium-stearate", "inactive")]


def test_a_unii_two_molecules_share_matches_neither():
    spl = {"doc_type": "HUMAN OTC DRUG LABEL", "ingredients": [{"role": "active", "name": "ESTRADIOL", "unii": "4TI98Z838E", "moiety": []},
                           {"role": "inactive", "name": "WATER", "unii": "059QF0KO0R", "moiety": []}],
           "active_lines": [], "purpose_lines": [], "purpose_rows": []}
    passed, report = _compile([_p("x", "medicine", "dailymed", SETID)], {SETID: spl})
    assert passed == []
    assert report["failures"][0]["matched"] == ["water"]


def test_the_gate_reports_every_failure_with_its_reason():
    two = {"doc_type": "HUMAN OTC DRUG LABEL", "ingredients": [{"role": "active", "name": "CAFFEINE", "unii": "3G6A5W338E", "moiety": []},
                           {"role": "inactive", "name": "WATER", "unii": "059QF0KO0R", "moiety": []},
                           {"role": "inactive", "name": "TALC", "unii": "7SEV7J4R1U", "moiety": []}],
           "active_lines": [], "purpose_lines": [], "purpose_rows": []}
    seed = [_p("gone", "medicine", "dailymed", SETID2), _p("thin", "medicine", "dailymed", SETID),
            _p("item", "drink", "wikidata", "Q1"), _p("missing", "drink", "wikidata", "Q2")]
    passed, report = _compile(seed, {SETID: two, SETID2: {"missing": True}},
                              {"Q1": {"P527": ["Q283", "Q60235"], "P186": ["Q999"]}, "Q2": {"missing": True}})
    assert passed == []
    reasons = {f["slug"]: f["reason"] for f in report["failures"]}
    assert reasons["gone"].startswith("label not found on DailyMed")
    assert reasons["thin"] == ("the label lists 3 ingredient(s); 2 are MoleculeFinder molecules, "
                               "fewer than 3")
    assert reasons["item"] == "Wikidata lists 3 ingredient(s); 2 are MoleculeFinder molecules, fewer than 3"
    assert reasons["missing"].startswith("item not found on Wikidata")
    assert report["seeded"] == 4 and report["failed"] == 4


def test_wikidata_parts_match_by_qid_in_wikidata_order():
    passed, _ = _compile([_p("diet-cola", "drink", "wikidata", "Q5")],
                         parts={"Q5": {"P527": ["Q283"], "P186": ["Q60235", "Q414484", "Q283", "Q42"]}})
    assert [(m["slug"], m["property"]) for m in passed[0]["molecules"]] == [
        ("water", "P527"), ("caffeine", "P186"), ("allura-red-ac", "P186")]
    assert passed[0]["listed"] == 5


def test_a_world_is_a_product_with_its_journey_captions():
    passed, _ = _compile([_p("morning-coffee", "drink", "world", "morning-coffee", "Morning coffee")])
    p = passed[0]
    assert p["source"] == {"type": "world", "world": "morning-coffee", "title": "Morning coffee",
                           "blurb": "What's in your cup."}
    assert [m["slug"] for m in p["molecules"]] == ["m1", "m2", "m3", "m4"]
    assert p["molecules"][0]["caption"] == "in your cup" and "caption" not in p["molecules"][1]


def test_attach_is_the_exact_reverse_of_every_product_list():
    passed, _ = _compile([_p("morning-coffee", "drink", "world", "morning-coffee", "Morning coffee"),
                          _p("example-cold", "medicine", "dailymed", SETID, "Example Cold")],
                         {SETID: dailymed.parse(SPL, SETID)})
    recs = [dict(r) for r in RECORDS]
    recs[0]["products"] = [{"slug": "stale"}]          # a stale list from a previous run goes
    products.attach_products(recs, passed)
    forward = {(p["slug"], m["slug"]) for p in passed for m in p["molecules"]}
    reverse = {(x["slug"], r["slug"]) for r in recs for x in r.get("products", [])}
    assert forward == reverse
    assert "products" not in next(r for r in recs if r["slug"] == "caffeine")   # in nothing: no field
    acet = next(r for r in recs if r["slug"] == "acetaminophen")
    assert acet["products"] == [{"slug": "example-cold", "name": "Example Cold", "kind": "medicine",
                                 "role": "active"}]


def test_compile_is_deterministic():
    seed = [_p("morning-coffee", "drink", "world", "morning-coffee"), _p("example-cold", "medicine", "dailymed", SETID)]
    labels = {SETID: dailymed.parse(SPL, SETID)}
    assert json.dumps(_compile(seed, labels)) == json.dumps(_compile(list(reversed(seed)), labels))


# ── the inputs travel with the snapshot ───────────────────────────────────────
def test_a_cached_label_is_an_input_and_a_pinned_build_refuses_a_changed_one(tmp_path):
    root = tmp_path / "raw_cache"
    label = root / "dailymed" / f"{products.SPL_PREFIX}-{SETID}.json"
    label.parent.mkdir(parents=True)
    label.write_text(json.dumps({"_mfetl_cache": 1, "fetched_at": "2026-10-22T00:00:00Z",
                                 "value": dailymed.parse(SPL, SETID)}))
    parts = root / "wikidata" / "product_parts.json"
    parts.parent.mkdir(parents=True)
    parts.write_text(json.dumps({"_mfetl_cache": 1, "entries": {"Q5": {"P527": ["Q283"], "fetched_at": "x"}}}))
    pointer = tmp_path / "inputs.json"
    fp = inputs.record(root, pointer, publish=True)
    assert f"dailymed/{label.name}" in json.loads((root / inputs.MANIFEST_NAME).read_text())["files"]
    assert inputs.verify(root, pointer) == fp
    label.write_text(label.read_text().replace("Example Brands LLC", "Someone Else"))
    with pytest.raises(inputs.InputsMismatch, match="dailymed"):
        inputs.verify(root, pointer)


# ── export ───────────────────────────────────────────────────────────────────
def test_export_writes_products_json_and_removes_it_without_a_seed(tmp_path, monkeypatch):
    from moleculefinder_etl import freshness
    monkeypatch.setattr(snapshot_export, "SNAPSHOTS", tmp_path)
    monkeypatch.setattr(freshness, "load", lambda path=None: {})
    recs = [{"cid": 2519, "slug": "caffeine", "title": "Caffeine", "synonyms": []}]
    snapshot_export.export(recs, {}, today="2026-10-22", products=[{"slug": "p", "molecules": []}])
    assert json.loads((tmp_path / "products.json").read_text()) == {"products": [{"slug": "p", "molecules": []}]}
    snapshot_export.export(recs, {}, today="2026-10-23")
    assert not (tmp_path / "products.json").exists()
    assert json.loads((tmp_path / "meta.json").read_text()) == {"refreshed": "2026-10-23"}


def test_warm_fetches_a_never_cached_wikidata_item_even_in_a_pinned_build(tmp_path, monkeypatch):
    monkeypatch.setenv("MFETL_INPUTS", "pinned")
    monkeypatch.setattr(products, "PARTS_CACHE", tmp_path / "wikidata" / "product_parts.json")
    asked = []
    monkeypatch.setattr(products.wikidata, "parts_for_qids",
                        lambda qids: asked.extend(qids) or {q: {"P527": ["Q283"], "P186": []} for q in qids})
    seed = [{"slug": "x", "name": "x", "kind": "drink", "source": "wikidata", "item": "Q5"}]
    products.warm(seed, [], lambda cids: None)
    assert asked == ["Q5"]
    products.warm(seed, [], lambda cids: None)          # cached now: a pinned build reuses it
    assert asked == ["Q5"]


def test_the_fetch_stage_warms_products_with_the_unii_expiry(tmp_path, monkeypatch):
    """The wiring: with a seed, the fetch stage warms the product inputs and fetches UNII codes
    through the batched per-CID cache with UNII_CACHE_TTL_DAYS (no network here)."""
    from moleculefinder_etl import pipeline
    from moleculefinder_etl.config import Settings
    seen: dict[str, object] = {}

    def recording(cids, prefix, fetch_missing, max_age_days=None):
        seen[prefix] = max_age_days
        return {}

    warmed = []
    monkeypatch.setattr(pipeline, "_fetch_cached", recording)
    monkeypatch.setattr(pipeline, "SEED_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "FETCHED", tmp_path / "fetched.json")
    (tmp_path / "canon.parquet").write_bytes(b"")
    monkeypatch.setattr(pipeline.canon_stage, "read_parquet", lambda: [{"cid": 2519}])
    monkeypatch.setattr(pipeline.pubchem, "pug_view", lambda cid, heading: None)
    seed = [{"slug": "x", "name": "x", "kind": "drink", "source": "world", "item": "morning-coffee"}]
    monkeypatch.setattr(pipeline.products, "load_seed", lambda: seed)

    def warm(s, cids, fetch_uniis):
        warmed.append((s, cids))
        fetch_uniis(cids)
    monkeypatch.setattr(pipeline.products, "warm", warm)
    pipeline.stage_fetch(Settings(None, None))
    assert warmed == [(seed, [2519])]
    assert seen["unii"] == pipeline.UNII_CACHE_TTL_DAYS


def test_export_refuses_records_listing_products_without_the_staged_products(tmp_path, monkeypatch):
    from moleculefinder_etl import pipeline
    molecules = tmp_path / "molecules.json"
    molecules.write_text(json.dumps([{"cid": 1, "slug": "a", "products": [{"slug": "p"}]}]))
    monkeypatch.setattr(pipeline, "MOLECULES", molecules)
    monkeypatch.setattr(pipeline, "PRODUCTS_STAGED", tmp_path / "missing.json")
    monkeypatch.setattr(pipeline, "_preflight", lambda m, guard=True: ({}, {}, None))
    monkeypatch.setattr(snapshot_export, "export", lambda *a, **k: pytest.fail("exported"))
    with pytest.raises(SystemExit, match="lists products"):
        pipeline.stage_export(None)
