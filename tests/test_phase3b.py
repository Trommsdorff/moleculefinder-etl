"""Phase 3B of the everyday chemistry plan (2026-11-14): the personal-care tranche, the aquatic hazard codes' words
from the EU CLP Regulation, and carboxymethyl cellulose drawn as its repeat unit. Garrett's rulings of 2026-11-14."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from rdkit import Chem

from moleculefinder_etl.config import SEEDS_DIR
from moleculefinder_etl.sources import registry
from moleculefinder_etl.transform import drawings, ghs, licence_gate, relationships

SNAP = Path(__file__).resolve().parents[1] / "data" / "snapshots"
FILTERS = ["avobenzone", "homosalate", "octisalate", "octocrylene"]
FLUORIDES = ["stannous-fluoride", "sodium-monofluorophosphate"]
SALTS = ["aluminum-chlorohydrate", "aluminum-sesquichlorohydrate", "aluminum-zirconium-tetrachlorohydrex-gly",
         "aluminum-zirconium-octachlorohydrex-gly", "aluminum-zirconium-trichlorohydrex-gly"]
CARE = FILTERS + FLUORIDES + SALTS
MONOGRAPH = {**{s: "M020" for s in FILTERS}, **{s: "M021" for s in FLUORIDES}, **{s: "M019" for s in SALTS}}


def _rec(slug):
    return json.loads((SNAP / "molecules" / f"{slug}.json").read_text())


# ── the eleven rows ──────────────────────────────────────────────────────────────────────────────
def test_the_tranche_is_the_plans_eleven_rows_in_one_batch():
    import csv
    with (SEEDS_DIR / "scope_b_core.csv").open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["batch"] == "2026-11-care"]
    assert sorted(r["molecule"].lower().replace(" ", "-") for r in rows) == sorted(CARE)
    # octinoxate and oxybenzone stay in the queue for a later tranche (the plan); titanium dioxide is not a row
    names = {r["molecule"].lower() for r in rows}
    assert not names & {"octinoxate", "oxybenzone", "titanium dioxide"}


def test_each_new_record_carries_its_monograph_approval_from_the_fdas_own_order():
    for slug in CARE:
        a = _rec(slug)["approval"]
        assert a["regulator"] == "US Food and Drug Administration", slug
        assert a["application"] == f"OTC Monograph {MONOGRAPH[slug]}", slug
        assert a["basis"].startswith("FDA OTC monograph.") and "Checked 2026-11-14" in a["basis"], slug
        assert a["source"].startswith("https://www.accessdata.fda.gov/drugsatfda_docs/omuf/"), slug
        assert "authorised" not in a, slug   # a monograph's order date is not an authorisation date


def test_the_salts_are_hand_modelled_with_no_structure_and_no_weight():
    for slug in SALTS:
        r = _rec(slug)
        assert r["hand_model"] and r["macromolecule"] and r["cid"] < 0, slug
        assert r["structure_svg"] is None and r["molecular_weight"] is None and r["molecular_formula"] is None, slug
        assert r["isomeric_smiles"] is None and r["scope_family"] == "inorganic", slug


def test_label_codes_reach_the_new_records_by_code():
    from moleculefinder_etl.transform import products
    subs = products.load_unii_substances()
    want = {"HPN8MZW13M": "aluminum-chlorohydrate", "UCN889409V": "aluminum-sesquichlorohydrate",
            "8O386558JE": "aluminum-zirconium-tetrachlorohydrex-gly",
            "P9D3YP29MY": "aluminum-zirconium-octachlorohydrex-gly",
            "T27D6T99LH": "aluminum-zirconium-trichlorohydrex-gly"}
    assert {k: subs[k] for k in want} == want
    # the filters and fluorides through the FDA's own table: every one is matched as a direct code on a label
    rows = json.loads((SNAP / "products.json").read_text())["products"]
    hit = {m["slug"]: m["match"] for p in rows for m in (p.get("molecules") or []) if m["slug"] in FILTERS + FLUORIDES}
    assert set(hit) == set(FILTERS + FLUORIDES) and set(hit.values()) <= {"unii", "moiety"}


def test_no_product_name_reaches_a_new_records_title_or_name_line():
    banned = {"crest", "sunscreen skincare", "dt collagen", "barbie", "extra-strength aim"}
    for slug in CARE:
        r = _rec(slug)
        shown = [r.get("title_synonym") or ""] + (r.get("display_synonyms") or []) + (r.get("wikidata_names") or [])
        assert not {n.lower() for n in shown} & banned, (slug, shown)


def test_the_two_new_lists_and_the_toothpaste_additions_carry_added_marks():
    hubs = yaml.safe_load((SEEDS_DIR / "product_hubs.yaml").read_text())
    # 2026-12-care (2026-11-15) adds titanium dioxide, octinoxate and oxybenzone after these (tests/test_care_tranche_2.py)
    assert [m["slug"] for m in hubs["sunscreen"]["molecules"]][:5] == FILTERS + ["zinc-oxide"]
    assert [m["slug"] for m in hubs["deodorant"]["molecules"]] == SALTS
    tooth = [m["slug"] for m in hubs["toothpaste"]["molecules"]]
    assert tooth[-3:-1] == FLUORIDES and tooth[-1] == "titanium-dioxide"   # titanium dioxide: 2026-12-care
    for hub in ("sunscreen", "deodorant", "toothpaste"):
        for m in hubs[hub]["molecules"]:
            assert m["presence"] == "added" and m["presence_note"], (hub, m)


# ── the hazard words ─────────────────────────────────────────────────────────────────────────────
def test_clp_words_exactly_the_five_codes_it_words_and_the_other_three_stay_codes():
    clp = ghs.clp_wording()
    assert clp == {
        "H400": "Very toxic to aquatic life",
        "H410": "Very toxic to aquatic life with long lasting effects",
        "H411": "Toxic to aquatic life with long lasting effects",
        "H412": "Harmful to aquatic life with long lasting effects",
        "H413": "May cause long lasting harmful effects to aquatic life",
    }
    words = {**ghs.hazard_wording(), **clp}
    assert not {"H333", "H401", "H402"} & set(words)


def test_the_eu_source_is_registered_displayable_and_cited_by_the_gate():
    assert registry.may_display("eu_clp")
    assert registry.SOURCES["eu_clp"]["licence_class"] == "acknowledged"
    assert registry.SOURCES["eu_clp"]["attribution"]
    m = {"slug": "x", "ghs": ghs.with_wording({"h_statements": ["H413"], "sources": ["echa"]})}
    cited = dict(licence_gate.molecule_citations(m))
    assert cited.get("x.ghs.h_wording_clp") == "eu_clp" and "x.ghs.h_wording" not in cited
    both = {"slug": "y", "ghs": ghs.with_wording({"h_statements": ["H302", "H410"], "sources": ["echa"]})}
    cited = dict(licence_gate.molecule_citations(both))
    assert cited["y.ghs.h_wording"] == "osha_hcs" and cited["y.ghs.h_wording_clp"] == "eu_clp"
    assert licence_gate.problems(licence_gate.molecule_citations(both)) == []


def test_a_record_worded_only_by_clp_names_no_hcs_source():
    out = ghs.with_wording({"h_statements": ["H413"], "sources": ["echa"]})
    assert out["h_wording"] == {"H413": "May cause long lasting harmful effects to aquatic life"}
    assert out["h_wording_clp"] == ["H413"] and "h_wording_source" not in out


# ── carboxymethyl cellulose ──────────────────────────────────────────────────────────────────────
def test_carboxymethyl_cellulose_is_drawn_as_its_repeat_unit_in_place_of_pubchems_drawing():
    r = _rec("carboxymethyl-cellulose")
    assert r["structure_svg"] is None and r["structure_svg_key"] is None and r["structure_parts"] is None
    u = r["structure_repeat_unit"]
    assert u["label"] == "Two units of the chain" and u["linkage"] == "beta-1,4" and u["group"] == "carboxymethyl"
    assert "varies from one grade to another" in u["line"] and "CID 24748" in u["replaces"]
    assert u["group_atoms"] and set(u["group_atoms"]).isdisjoint(u["linkage_atoms"])
    assert "class='mf-linkage'" in u["layer"]
    # Phase 3B kept PubChem's identifiers; Garrett's decision 5 (2026-11-15) dropped the fragment pair's formula, weight,
    # SMILES and groups in the 2026-12-care tranche (tests/test_care_tranche_2.py). The CID stays.
    assert r["cid"] == 24748 and r["molecular_formula"] is None


def test_the_unit_is_cellulose_with_one_carboxymethyl_group_stereo_included():
    units = drawings.load_repeat_seed()
    cmc, cell = units["carboxymethyl-cellulose"]["smiles"], units["cellulose"]["smiles"]
    stripped = Chem.MolFromSmiles(cmc.replace("COCC(=O)O", "CO"))
    assert Chem.MolToSmiles(stripped) == Chem.MolToSmiles(Chem.MolFromSmiles(cell))
    m = Chem.MolFromSmiles(cmc)
    assert len(m.GetSubstructMatches(Chem.MolFromSmarts(units["carboxymethyl-cellulose"]["group_smarts"]))) == 1


def test_a_repeat_unit_may_replace_a_drawing_only_when_it_says_why():
    recs = [{"slug": "a", "cid": 1, "structure_svg": "<svg/>", "structure_svg_key": "k"}]
    spec = dict(drawings.load_repeat_seed()["cellulose"])
    with pytest.raises(drawings.DrawingSeedError, match="replaces"):
        drawings.attach_repeat_units(recs, {}, units={"a": spec})
    assert drawings.clear_replaced_drawings(recs, units={"a": {**spec, "replaces": "Why it replaces the drawing."}}) == ["a"]
    assert recs[0]["structure_svg"] is None and recs[0]["structure_svg_key"] is None


def test_the_new_lines_are_curated_and_long_enough_to_be_the_description():
    for slug in CARE:
        r = _rec(slug)
        assert r["why_it_matters"]["text"] == r["description"], slug
        assert 100 <= len(r["description"]) <= 200, slug
        assert "—" not in r["description"] and "–" not in r["description"], slug


def test_approvals_compile_on_the_catalog():
    recs = [{"slug": s} for s in CARE] + [{"slug": s} for s in
                                          ("orforglipron", "meldonium", "phenibut", "clenbuterol", "clostebol", "flunitrazepam",
                                           "titanium-dioxide", "octinoxate", "oxybenzone")]   # the last three: 2026-12-care
    relationships.attach_approvals(recs)
    assert all(r.get("approval") for r in recs)
